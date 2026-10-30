"""
Camada de checagem de fatos — G1 Fato ou Fake + Agência Lupa.

- Coleta apenas títulos, links, datas e resumos públicos.
- Extrai o veredito do próprio título (não há ClaimReview estruturado).
- NÃO rotula matérias como fake: apenas sinaliza "tema já checado" e o veredito
  da checagem, sempre com link para a fonte original.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone

import feedparser
import requests

UA = "Balanco/0.2 (+news aggregator; local)"
TIMEOUT = 30

G1_RSS = "https://g1.globo.com/rss/g1/fato-ou-fake/"
LUPA_API = "https://www.agencialupa.org/wp-json/wp/v2/posts"
LUPA_VERIFICACAO_CAT = 142  # categoria "Verificação"


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


# ─────────────────────── veredito ───────────────────────
def verdict_from_title(title: str) -> str:
    """Classifica o veredito a partir do título. Cauteloso: default = 'checagem'."""
    t = " " + title.lower() + " "

    # rodada de checagem (cita os dois selos) não é um veredito único
    if "#fato" in t and "#fake" in t:
        return "checagem"

    # verdadeiro
    if "#fato" in t or "é #fato" in t or re.search(r"\bé verdade(?:iro)?\b", t) or "confirma que" in t:
        return "verdadeiro"

    # falso
    if any(k in t for k in ["#fake", "é falso", "é falsa", "não é verdade", "não procede",
                            "notícia falsa", "documento falso", "boato", "não aconteceu",
                            "é mentira"]):
        return "falso"

    # enganoso / fora de contexto
    if any(k in t for k in ["não indica", "não mostra", "não tem relação", "não está relacionad",
                            "distorce", "fora de contexto", "sem contexto", "enganos",
                            "imprecis", "exagera", "subestima", "não é bem assim",
                            "não comprova", "não prova", "não é atual", "desatualizad"]):
        return "enganoso"

    return "checagem"


def verdict_label(v: str) -> str:
    return {"falso": "Falso", "verdadeiro": "Verdadeiro",
            "enganoso": "Enganoso", "checagem": "Checagem"}.get(v, "Checagem")


# ─────────────────────── coletores ───────────────────────
def fetch_g1(limit: int = 100) -> list[dict]:
    r = requests.get(G1_RSS, timeout=TIMEOUT, headers={"User-Agent": UA})
    r.raise_for_status()
    d = feedparser.parse(r.content)
    out = []
    for e in d.entries[:limit]:
        title = _clean(e.get("title"))
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        pp = e.get("published_parsed")
        dt = datetime.fromtimestamp(
            __import__("time").mktime(pp), tz=timezone.utc) if pp else datetime.now(timezone.utc)
        out.append({
            "checker": "G1 Fato ou Fake",
            "title": title,
            "link": link,
            "summary": _clean(e.get("summary"))[:400],
            "published": _iso(dt),
            "verdict": verdict_from_title(title),
        })
    return out


def fetch_lupa(limit: int = 100) -> list[dict]:
    params = {
        "categories": LUPA_VERIFICACAO_CAT,
        "per_page": min(limit, 100),
        "_fields": "id,date,link,title,excerpt",
    }
    r = requests.get(LUPA_API, params=params, timeout=TIMEOUT, headers={"User-Agent": UA})
    r.raise_for_status()
    out = []
    for p in r.json():
        title = _clean(p.get("title", {}).get("rendered"))
        link = p.get("link", "")
        if not title or not link:
            continue
        try:
            dt = datetime.fromisoformat(p["date"])
        except Exception:
            dt = datetime.now(timezone.utc)
        out.append({
            "checker": "Agência Lupa",
            "title": title,
            "link": link,
            "summary": _clean(p.get("excerpt", {}).get("rendered"))[:400],
            "published": _iso(dt),
            "verdict": verdict_from_title(title),
        })
    return out


def fetch_all(g1_limit: int = 100, lupa_limit: int = 100) -> list[dict]:
    items: list[dict] = []
    for fn, lim in ((fetch_g1, g1_limit), (fetch_lupa, lupa_limit)):
        try:
            items.extend(fn(lim))
        except Exception as ex:
            print(f"  [checagem] falha em {fn.__name__}: {ex}")
    # dedup por link
    seen, uniq = set(), []
    for it in items:
        if it["link"] in seen:
            continue
        seen.add(it["link"])
        uniq.append(it)
    uniq.sort(key=lambda x: x["published"], reverse=True)
    return uniq
