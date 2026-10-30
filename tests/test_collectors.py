"""Coletores: canonização, editoria, datas, parse de RSS/sitemap (com HTTP simulado)."""
import collectors
from collectors import (
    _canonical_link,
    _collect_sitemap_url,
    _parse_date,
    _section_from_url,
    fetch_rss,
    fetch_sitemap,
)

RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Teste</title>
<item><title>Primeira notícia de teste</title><link>https://exemplo.com/a?utm_source=x</link><pubDate>Thu, 30 Oct 2026 12:00:00 GMT</pubDate><description>Resumo <b>um</b></description></item>
<item><title></title><link>https://exemplo.com/empty</link></item>
<item><title>Segunda matéria</title><link>https://redir.folha.com.br/redir/online/x/*https://www1.folha.uol.com.br/mundo/2026/10/noticia.shtml</link></item>
</channel></rss>""".encode()

SITEMAP_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
<url><loc>https://exemplo.com/politica/materia-um</loc><news:news><news:title>Matéria um sobre política</news:title><news:publication_date>2026-10-30T10:00:00+00:00</news:publication_date></news:news></url>
<url><loc>https://exemplo.com/economia/outra-noticia</loc><news:news><news:title>Outra sobre economia</news:title><news:publication_date>2026-10-29T10:00:00+00:00</news:publication_date></news:news></url>
</urlset>""".encode()

INDEX_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://exemplo.com/2026-10-30-gnews.xml</loc></sitemap>
<sitemap><loc>https://exemplo.com/2026-10-29-gnews.xml</loc></sitemap>
</sitemapindex>""".encode()


def fake_http_factory(mapping):
    def _fake(url, store=None):
        body = mapping.get(url, b"")
        return body, 200, '"etag-x"', None, 5
    return _fake


def test_canonical_link_strips_utm_and_fragment():
    assert _canonical_link("https://x.com/a?utm_source=rss&x=1#top") == "https://x.com/a?x=1"


def test_canonical_link_resolves_folha_redirect():
    u = "https://redir.folha.com.br/redir/online/x/*https://www1.folha.uol.com.br/mundo/2026/10/n.shtml"
    assert _canonical_link(u) == "https://www1.folha.uol.com.br/mundo/2026/10/n.shtml"


def test_section_from_url():
    assert _section_from_url("https://x.com/politica/materia") == "politica"
    # slug de matéria não vira editoria
    assert _section_from_url("https://x.com/ativistas-pro-vida-coletam-100-mil-assinaturas-contra-lei") == ""
    # prefixo "web" da piauí é ignorado
    assert _section_from_url("https://piaui.uol.com.br/web/alguma-coisa/") == "alguma-coisa"


def test_parse_date_iso_and_none():
    assert _parse_date("2026-10-30T10:00:00Z").year == 2026
    assert _parse_date(None) is None
    assert _parse_date("") is None


def test_fetch_rss_parses_and_skips_empty(monkeypatch):
    monkeypatch.setattr(collectors, "_http", fake_http_factory({"u": RSS_FIXTURE}))
    items, stats = fetch_rss({"rss": "u"}, store=None)
    assert stats["status"] == "ok"
    assert len(items) == 2
    by_title = {a["title"]: a for a in items}
    assert by_title["Primeira notícia de teste"]["link"] == "https://exemplo.com/a"
    assert "<b>" not in by_title["Primeira notícia de teste"]["summary"]
    assert by_title["Segunda matéria"]["link"].startswith("https://www1.folha.uol.com.br/")


def test_fetch_sitemap_parses_news(monkeypatch):
    monkeypatch.setattr(collectors, "_http", fake_http_factory({"u": SITEMAP_FIXTURE}))
    items, stats = fetch_sitemap({"rss": "u"}, store=None)
    assert stats["status"] == "ok"
    assert len(items) == 2
    assert items[0]["title"] == "Matéria um sobre política"  # mais recente primeiro
    assert items[0]["section"] == "politica"


def test_sitemap_index_prefers_recent(monkeypatch):
    mapping = {
        "idx": INDEX_FIXTURE,
        "https://exemplo.com/2026-10-30-gnews.xml": SITEMAP_FIXTURE,
        "https://exemplo.com/2026-10-29-gnews.xml": SITEMAP_FIXTURE,
    }
    monkeypatch.setattr(collectors, "_http", fake_http_factory(mapping))
    stats: dict = {"status": "ok", "ms": 0, "n_urls": 0, "n_304": 0, "errors": []}
    out = _collect_sitemap_url("idx", limit=30, store=None, stats=stats)
    assert len(out) == 4  # 2 filhos x 2 urls
    assert stats["n_urls"] == 3  # índice + 2 filhos


def test_http_304_returns_none(monkeypatch):
    def _fake(url, store=None):
        return None, 304, None, None, 3
    monkeypatch.setattr(collectors, "_http", _fake)
    items, stats = fetch_sitemap({"rss": "u"}, store=None)
    assert items == []
    assert stats["n_304"] == 1
