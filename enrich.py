"""
Enriquecimento de matérias (Fase 3.1): meta description + corpo, só de conteúdo público.

- Lê JSON-LD `articleBody` → parágrafos do <article> → fallback meta description.
- Detecta muro (marcadores + corpo curto) e marca `paywalled`, sem insistir.
- robots.txt de editorias é ignorado por decisão do dono (uso pessoal, baixo volume);
  o que evita bloqueio de verdade é delay + cache + conditional — mantidos.
- Sem burlar muro: só conteúdo servido publicamente (sem cookie/UA falso, espelho
  de arquivo ou remoção de overlay). O que é pago continua pago.
- Texto público pode alimentar o matching e aparecer em trechos maiores, sempre
  com atribuição + link (a restrição "corpo só para máquina" foi removida).
"""
from __future__ import annotations

import html
import json
import re
import time
from html.parser import HTMLParser

import requests

UA = "Balanco/0.2 (+news aggregator; local)"
TIMEOUT = 25
BODY_TTL_DAYS = 7
BODY_CAP = 4000
RATE_DELAY_S = 2.0

PAYWALL_MARKS = ["assine", "para continuar lendo", "exclusivo para assinantes",
                 "já é assinante", "faça login", "continue lendo", "paywall"]
# muro "suave": o corpo extraído é só o apelo de assinatura (Núcleo e afins)
BODY_PAYWALL_MARKS = ["sua ajuda é fundamental", "para continuarmos fazendo",
                      "benefícios exclusivos", "seja assinante",
                      "apoie o jornalismo", "assine para continuar"]


class _ArticleParser(HTMLParser):
    """Extrai meta description, JSON-LD e parágrafos (stdlib, sem bs4)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = ""
        self.author = ""
        self.ld_blocks: list[str] = []
        self.paras: list[str] = []
        self._in_ld = False
        self._ld_buf: list[str] = []
        self._in_article = 0
        self._in_p = False
        self._p_buf: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key == "description" and not self.meta:
                self.meta = (a.get("content") or "").strip()[:600]
            if key in {"author", "article:author", "parsely-author",
                       "sailthru.author", "dc.creator", "cxenseparse:author"} \
                    and not self.author:
                val = (a.get("content") or "").strip()
                if val and not val.lower().startswith("http"):
                    self.author = val[:120]
        if tag == "script":
            self._in_script = True
            if "ld+json" in (a.get("type") or ""):
                self._in_ld = True
                self._ld_buf = []
        if tag == "article":
            self._in_article += 1
        if tag == "p" and self._in_article > 0 and not self._in_script:
            self._in_p = True
            self._p_buf = []

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False
            if self._in_ld:
                self._in_ld = False
                self.ld_blocks.append("".join(self._ld_buf))
        if tag == "article" and self._in_article > 0:
            self._in_article -= 1
        if tag == "p" and self._in_p:
            self._in_p = False
            txt = re.sub(r"\s+", " ", "".join(self._p_buf)).strip()
            if len(txt) > 40:
                self.paras.append(txt)

    def handle_data(self, data):
        if self._in_ld:
            self._ld_buf.append(data)
        elif self._in_p:
            self._p_buf.append(data)


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _ld_author(blocks: list[str]) -> str:
    for b in blocks:
        try:
            d = json.loads(b.strip())
        except Exception:
            continue
        items = d if isinstance(d, list) else [d]
        for it in items:
            if not isinstance(it, dict):
                continue
            nodes = [it] + [x for x in it.get("@graph", []) if isinstance(x, dict)]
            for n in nodes:
                au = n.get("author")
                if isinstance(au, dict):
                    name = au.get("name")
                    if name:
                        return _clean(str(name))[:120]
                elif isinstance(au, list):
                    for x in au:
                        if isinstance(x, dict) and x.get("name"):
                            return _clean(str(x["name"]))[:120]
                elif isinstance(au, str) and au.strip():
                    return _clean(au)[:120]
    return ""


def _ld_article_body(blocks: list[str]) -> tuple[str, bool]:
    """Retorna (articleBody, isAccessibleForFree)."""
    body, free = "", True
    for b in blocks:
        try:
            d = json.loads(b.strip())
        except Exception:
            continue
        items = d if isinstance(d, list) else [d]
        for it in items:
            if not isinstance(it, dict):
                continue
            nodes = [it] + [x for x in it.get("@graph", []) if isinstance(x, dict)]
            for n in nodes:
                t = str(n.get("@type", ""))
                if "NewsArticle" not in t and "Article" not in t:
                    continue
                if n.get("articleBody") and len(str(n["articleBody"])) > len(body):
                    body = str(n["articleBody"])
                acc = n.get("isAccessibleForFree")
                if acc is False:
                    free = False
    return body, free


def parse_article(html_text: str) -> dict:
    """Extrai {meta, body, paywalled, method} de um HTML. Puro, sem rede (testável)."""
    p = _ArticleParser()
    try:
        p.feed(html_text or "")
    except Exception:
        pass
    meta = _clean(p.meta)
    body, free = _ld_article_body(p.ld_blocks)
    method = "jsonld" if body else ""
    if not body and p.paras:
        body, method = "\n\n".join(p.paras)[:BODY_CAP], "p-tags"
    if not body:
        body, method = meta, "meta"
    low = (html_text or "").lower()
    marked = any(m in low for m in PAYWALL_MARKS)
    body_low = (body or "").lower()
    soft = any(m in body_low for m in BODY_PAYWALL_MARKS)
    paywalled = ((marked or not free) and len(body) < 500) or \
        (soft and len(body) < 1500)
    author = _clean(p.author or _ld_author(p.ld_blocks))[:120]
    return {"meta": meta, "body": _clean(body)[:BODY_CAP],
            "paywalled": paywalled, "method": method or "none",
            "author": author}


def _http_get(url: str):
    r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
    r.raise_for_status()
    return r.text


def fetch_body(url: str, store=None) -> dict:
    """Busca e parseia o corpo (com cache de 7 dias). Retorna {meta, body, paywalled, method}."""
    if store is not None:
        hit = store.get_body(url)
        if hit:
            return hit
    try:
        result = parse_article(_http_get(url))
    except Exception as e:
        result = {"meta": "", "body": "", "paywalled": False,
                  "method": "error", "error": str(e)[:150]}
    if store is not None and result.get("method") not in ("error",):
        store.save_body(url, result)
    return result


def fetch_author(url: str, timeout: int = 8) -> str:
    """Só o autor público da página (meta/JSON-LD), para os cartões de opinião."""
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA})
        p = _ArticleParser()
        p.feed(r.text or "")
        return _clean(p.author or _ld_author(p.ld_blocks))[:120]
    except Exception:
        return ""


def _use_result(a: dict, r: dict) -> tuple[int, int, int]:
    """Aplica meta/corpo ao artigo. Retorna (filled, bodies, paywalled)."""
    paywalled = 1 if r.get("paywalled") else 0
    bodies = 1 if (r.get("body") and not r.get("paywalled")) else 0
    filled = 0
    if not a.get("summary"):
        # meta é o resumo editorial; se faltar, usa o lead do corpo público
        text = r.get("meta") or (r.get("body") or "")
        if text:
            a["summary"] = re.sub(r"\s+", " ", text).strip()[:600]
            filled = 1
    if not a.get("author") and r.get("author"):
        a["author"] = r["author"]
    return filled, bodies, paywalled


def enrich_articles(articles: list[dict], store, cap: int = 40,
                    delay: float = RATE_DELAY_S,
                    priority_sources=None) -> dict:
    """Preenche summary via meta/lead e banca corpos (Fase 3.5).

    Prioriza: sem resumo → fontes de sitemap (que vêm sem dek) → mais recentes.
    Baixa em paralelo por host (polidez por domínio), respeitando `cap`.
    Retorna {"filled", "bodies", "paywalled"}.
    """
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import urlparse

    prio = set(priority_sources or [])
    ordered = sorted(
        articles,
        key=lambda a: (0 if not a.get("summary") else 1,
                       0 if a.get("source_id") in prio else 1,
                       -float(a.get("ts") or 0)))
    stats = {"filled": 0, "bodies": 0, "paywalled": 0}

    # 1) cache hit: sem rede
    queue, done = [], 0
    for a in ordered:
        if done >= cap:
            break
        hit = store.get_body(a["link"]) if store is not None else None
        if hit:
            f, b, p = _use_result(a, hit)
            stats["filled"] += f; stats["bodies"] += b; stats["paywalled"] += p
            continue
        queue.append(a)
        done += 1

    # 2) rede: agrupa por host e paraleliza entre hosts
    by_host: dict[str, list] = {}
    for a in queue:
        by_host.setdefault(urlparse(a["link"]).netloc, []).append(a)

    def work(items):
        # rede/parse sem tocar no SQLite (conexão é presa à thread)
        out = []
        for a in items:
            time.sleep(delay)
            out.append((a, fetch_body(a["link"], None)))
        return out

    results = []
    if by_host:
        with ThreadPoolExecutor(max_workers=min(6, len(by_host))) as ex:
            for chunk in ex.map(work, by_host.values()):
                results.extend(chunk)
    # grava cache e aplica na thread principal (SQLite seguro)
    for a, r in results:
        if store is not None and r.get("method") not in (None, "error"):
            store.save_body(a["link"], r)
        f, b, pw = _use_result(a, r)
        stats["filled"] += f; stats["bodies"] += b; stats["paywalled"] += pw
    return stats
