"""
Enriquecimento de matérias (Fase 3.1): meta description + corpo, só de conteúdo público.

- Lê JSON-LD `articleBody` → parágrafos do <article> → fallback meta description.
- Detecta muro (marcadores + corpo curto) e marca `paywalled`, sem insistir.
- robots.txt de editorias é ignorado por decisão do dono (uso pessoal, baixo volume);
  o que evita bloqueio de verdade é delay + cache + conditional — mantidos.
- Regra de exibição: corpo alimenta só máquina (cluster/matching futuros);
  na tela, meta description ou trecho curto com atribuição + link.
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


class _ArticleParser(HTMLParser):
    """Extrai meta description, JSON-LD e parágrafos (stdlib, sem bs4)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = ""
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
        if tag == "meta" and a.get("name", "").lower() == "description" and not self.meta:
            self.meta = (a.get("content") or "").strip()[:600]
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
    paywalled = (marked or not free) and len(body) < 500
    return {"meta": meta, "body": _clean(body)[:BODY_CAP],
            "paywalled": paywalled, "method": method or "none"}


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


def enrich_articles(articles: list[dict], store, cap: int = 40,
                    delay: float = RATE_DELAY_S) -> dict:
    """Preenche summary vazio via meta e banca corpos no cache (para uso interno).

    Prioriza artigos sem resumo. Retorna {"filled": n, "bodies": n, "paywalled": n}.
    """
    stats = {"filled": 0, "bodies": 0, "paywalled": 0}
    ordered = sorted(articles, key=lambda a: 0 if not a.get("summary") else 1)
    done = 0
    for a in ordered:
        if done >= cap:
            break
        if store is not None and store.get_body(a["link"]):
            r = store.get_body(a["link"])
        else:
            if done:
                time.sleep(delay)
            r = fetch_body(a["link"], store)
            done += 1
        if r.get("paywalled"):
            stats["paywalled"] += 1
        if r.get("body") and not r.get("paywalled"):
            stats["bodies"] += 1
        if not a.get("summary") and r.get("meta"):
            a["summary"] = r["meta"][:600]
            stats["filled"] += 1
    return stats
