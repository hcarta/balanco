"""
Coletores plugáveis para fontes que não têm RSS público.

Cada fonte declara um `fetcher` em sources.yaml:
  - rss       → RSS/Atom comum (feedparser)
  - sitemap   → Google News sitemap (urlset) ou índice de sitemaps (sitemapindex)

Regras de ouro:
  - Usa apenas endpoints machine-readable publicados pelo veículo (RSS/sitemap).
  - Não busca corpo de matéria nem contorna paywall.
  - Só extrai manchete, link, data e (quando existe) imagem/section.
  - Identifica-se com User-Agent próprio e respeita timeout/limite.
"""
from __future__ import annotations

import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import feedparser
import requests

UA = "Balanco/0.2 (+news aggregator; local)"
TIMEOUT = 30
RETRIES = 1  # 1 retry com backoff (Fase 1.3)

NS = {
    "s": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "n": "http://www.google.com/schemas/sitemap-news/0.9",
    "image": "http://www.google.com/schemas/sitemap-image/1.1",
}

_TOKEN = re.compile(r"[a-zà-ú0-9]+", re.I)


def _http(url: str, store=None):
    """GET com headers condicionais do cache e 1 retry.

    Retorna (content|None, status, etag, last_modified, ms).
    content=None significa 304 Not Modified (nada mudou).
    """
    headers = {"User-Agent": UA}
    if store is not None:
        headers.update(store.cond_headers(url))
    last = None
    for attempt in range(RETRIES + 1):
        t0 = time.monotonic()
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=headers)
            ms = int((time.monotonic() - t0) * 1000)
            if r.status_code == 304:
                return None, 304, None, None, ms
            r.raise_for_status()
            etag, lm = r.headers.get("ETag"), r.headers.get("Last-Modified")
            if store is not None:
                store.save_http(url, etag, lm)
            return r.content, r.status_code, etag, lm, ms
        except Exception as e:
            last = e
            ms = int((time.monotonic() - t0) * 1000)
            if attempt < RETRIES:
                time.sleep(1.5 * (attempt + 1))
    raise last


def _get(url: str) -> bytes:
    content, status, _, _, _ = _http(url)
    return content or b""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _to_ts(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _canonical_link(url: str) -> str:
    """Resolve redirect da Folha e remove fragmento/utm — melhora dedup e section."""
    url = (url or "").strip()
    if not url:
        return ""
    if "redir.folha.com.br" in url and "*" in url:
        url = url.rsplit("*", 1)[-1]
    url = url.split("#", 1)[0]
    url = re.sub(r"[?&](utm_[^=&]+|fbclid|gclid)=[^&]*", "", url)
    return url.rstrip("?&")


def _section_from_url(url: str) -> str:
    """Primeiro segmento de caminho útil vira a editoria (politica, economia...)."""
    try:
        path = urllib.parse.urlparse(url).path.strip("/")
    except Exception:
        return ""
    if not path:
        return ""
    first = path.split("/")[0]
    if first in {"noticia", "noticias", "mundo", "brasil", "web"} or len(first) < 2:
        parts = path.split("/")
        first = parts[1] if len(parts) > 1 else first
    # descarta slug de matéria (muitos hífens) — só aceita nomes de editoria
    if first.count("-") > 2 or len(first) > 24:
        return ""
    return first


def _title_from_slug(url: str) -> str:
    path = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    slug = path.rsplit(".", 1)[0].replace("-", " ").strip()
    return slug[:1].upper() + slug[1:] if slug else ""


# ───────────────────────── RSS ─────────────────────────
def fetch_rss(source: dict, limit: int = 30, store=None) -> tuple[list[dict], dict]:
    stats: dict = {"status": "ok", "ms": 0, "n_urls": 0, "n_304": 0, "errors": []}
    try:
        content, status, _, _, ms = _http(source["rss"], store)
    except Exception as e:
        stats.update(status="error", errors=[str(e)[:200]])
        return [], stats
    stats["ms"] = ms
    stats["n_urls"] = 1
    if content is None:  # 304
        stats["n_304"] = 1
        return [], stats
    d = feedparser.parse(content)
    out = []
    for e in d.entries:
        title = _clean(e.get("title"))
        link = _canonical_link(e.get("link") or "")
        if not title or not link:
            continue
        pp = e.get("published_parsed") or e.get("updated_parsed")
        dt = datetime.fromtimestamp(time.mktime(pp), tz=timezone.utc) if pp else datetime.now(timezone.utc)
        summary = _clean(e.get("summary") or e.get("description"))
        out.append({
            "title": title,
            "link": link,
            "summary": summary[:600],
            "published": _iso(dt),
            "ts": _to_ts(dt),
            "section": _section_from_url(link),
        })
    out.sort(key=lambda a: a["ts"], reverse=True)
    return out[:limit], stats


# ─────────────────────── SITEMAPS ───────────────────────
def _collect_sitemap_url(url: str, limit: int, depth: int = 0,
                         store=None, stats: dict | None = None) -> list[dict]:
    if depth > 2:
        return []
    try:
        content, status, _, _, ms = _http(url, store)
    except Exception as e:
        if stats is not None:
            stats["errors"].append(f"{url[:80]}: {e}"[:200])
        return []
    if stats is not None:
        stats["n_urls"] += 1
        stats["ms"] += ms
        if content is None:  # 304: nada mudou neste sitemap
            stats["n_304"] += 1
            return []
    root = ET.fromstring(content)
    name = _local(root.tag)

    if name == "sitemapindex":
        children = [c.findtext("s:loc", namespaces=NS) for c in root.findall("s:sitemap", NS)]
        children = [c for c in children if c]
        if not children:
            return []
        # prefere news sitemaps (-gnews / news)
        gnews = [c for c in children if "gnews" in c or "news" in c]
        pool = gnews or children
        # ordena por data embutida no nome do arquivo (YYYY-MM-DD), mais recente primeiro
        def _date_key(loc: str) -> str:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", loc)
            return m.group(1) if m else ""
        pool = sorted(pool, key=_date_key, reverse=True)[:3]
        out = []
        for c in pool:
            try:
                out.extend(_collect_sitemap_url(c, limit=limit, depth=depth + 1,
                                                store=store, stats=stats))
            except Exception:
                continue
        return out

    if name != "urlset":
        return []

    out = []
    for u in root.findall("s:url", NS):
        loc = u.findtext("s:loc", namespaces=NS)
        if not loc:
            continue
        news = u.find("n:news", NS)
        title = ""
        dt = None
        if news is not None:
            title = _clean(news.findtext("n:title", namespaces=NS))
            dt = _parse_date(news.findtext("n:publication_date", namespaces=NS))
        if not dt:
            dt = _parse_date(u.findtext("s:lastmod", namespaces=NS))
        if dt is None:
            dt = datetime.now(timezone.utc)
        if not title:
            title = _title_from_slug(loc)
        img = u.findtext("image:image/image:loc", namespaces=NS)
        link = _canonical_link(loc)
        out.append({
            "title": title,
            "link": link,
            "summary": "",
            "published": _iso(dt),
            "ts": _to_ts(dt),
            "section": _section_from_url(link),
            "image": img or "",
        })
    return out


def fetch_sitemap(source: dict, limit: int = 30, store=None) -> tuple[list[dict], dict]:
    stats: dict = {"status": "ok", "ms": 0, "n_urls": 0, "n_304": 0, "errors": []}
    out = _collect_sitemap_url(source["rss"], limit=limit, store=store, stats=stats)
    # dedup por link e corta pelos mais recentes
    seen, uniq = set(), []
    for a in sorted(out, key=lambda x: x["ts"], reverse=True):
        if a["link"] in seen:
            continue
        seen.add(a["link"])
        uniq.append(a)
        if len(uniq) >= limit:
            break
    if stats["errors"] and not uniq:
        stats["status"] = "error"
    elif stats["errors"]:
        stats["status"] = "partial"
    return uniq, stats


# ─────────────────────── DISPATCH ───────────────────────
def collect_one(source: dict, limit: int = 30, store=None) -> tuple[list[dict], dict]:
    """Retorna (itens frescos parseados, stats). Com store, usa HTTP condicional."""
    fetcher = (source.get("fetcher") or "rss").lower()
    if fetcher == "sitemap":
        return fetch_sitemap(source, limit=limit, store=store)
    return fetch_rss(source, limit=limit, store=store)
