"""Enriquecimento (Fase 3): parse de HTML, detecção de muro, cache e editorias."""
import app
from app import section_label
from enrich import enrich_articles, parse_article

OPEN_HTML = """<html><head>
<meta name="description" content="Resumo público da matéria aqui.">
<script type="application/ld+json">{"@type":"NewsArticle","headline":"T",
"articleBody":"Primeiro parágrafo completo. Segundo parágrafo completo."}</script>
</head><body><article><p>Primeiro parágrafo completo.</p></article></body></html>"""

WALL_HTML = """<html><head>
<meta name="description" content="Chamada pública curta.">
<script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":false}</script>
</head><body><div class="paywall">assine para continuar lendo</div>
<article><p>Texto.</p></article></body></html>"""

PTAGS_HTML = """<html><head></head><body><article>
<p>Primeiro parágrafo longo o suficiente para ser capturado pelo parser sem JSON-LD por perto.</p>
<p>Segundo parágrafo também longo o suficiente para entrar no corpo extraído.</p>
</article></body></html>"""


def test_parse_jsonld_body():
    r = parse_article(OPEN_HTML)
    assert not r["paywalled"]
    assert r["method"] == "jsonld"
    assert "Primeiro parágrafo" in r["body"]
    assert r["meta"].startswith("Resumo público")


def test_parse_paywall_flagged_no_body():
    r = parse_article(WALL_HTML)
    assert r["paywalled"]
    assert r["body"] == "" or len(r["body"]) < 500
    assert r["meta"] == "Chamada pública curta."  # meta sobrevive ao muro


def test_parse_ptags_fallback():
    r = parse_article(PTAGS_HTML)
    assert not r["paywalled"]
    assert r["method"] == "p-tags"
    assert "Primeiro parágrafo" in r["body"]


def test_enrich_fills_missing_summary_and_caches(tmp_path):
    from store import Store
    s = Store(path=str(tmp_path / "c.db"))
    calls = []

    import enrich as E
    orig = E._http_get
    E._http_get = lambda url: (calls.append(url), OPEN_HTML)[1]
    try:
        arts = [{"title": "T1", "link": "https://x/1", "summary": ""},
                {"title": "T2", "link": "https://x/2", "summary": "já tem"}]
        stats = enrich_articles(arts, s, cap=10, delay=0)
        assert arts[0]["summary"].startswith("Resumo público")
        assert arts[1]["summary"] == "já tem"
        assert stats["filled"] == 1 and stats["bodies"] == 2
        # segunda rodada usa cache (sem HTTP)
        E._http_get = lambda url: (_ for _ in ()).throw(AssertionError("rede!"))
        stats2 = enrich_articles([{"title": "T1", "link": "https://x/1", "summary": ""}], s, cap=10, delay=0)
        assert stats2["filled"] == 1
    finally:
        E._http_get = orig
    s.close()


def test_section_label():
    assert section_label("politica") == "Política"
    assert section_label("republica") == "Republica"  # fora do mapa: capitaliza
    assert section_label("vozes") == "Opinião"
    assert section_label("Política") == "Política"  # com acento
    assert section_label("") == "Geral"
    assert section_label(None) == "Geral"


def test_build_keeps_image_and_section_label():
    arts = [
        {"title": "A aprova plano de recuperação", "link": "https://x/1",
         "summary": "", "published": "2026-10-30T00:00:00+00:00", "ts": 1.0,
         "section": "economia", "image": "https://img/x.jpg",
         "source_id": "v", "source_name": "V", "base_bias": 0.0},
        {"title": "A aprova plano de recuperação extrajudicial", "link": "https://x/2",
         "summary": "", "published": "2026-10-30T00:00:00+00:00", "ts": 1.0,
         "section": "mercados", "image": "",
         "source_id": "w", "source_name": "W", "base_bias": 0.0},
    ]
    srcs = [{"id": "v", "factuality": "high"}, {"id": "w", "factuality": "high"}]
    stories = app.build(srcs, arts, {}, thresh=0.2)
    assert len(stories) == 1
    assert stories[0]["section_label"] in ("Economia", "Mercado")
    imgs = [a["image"] for a in stories[0]["articles"]]
    assert "https://img/x.jpg" in imgs
    assert stories[0]["articles"][0]["section_label"] in ("Economia", "Mercado")
