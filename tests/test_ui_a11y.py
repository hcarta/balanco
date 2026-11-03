"""Fase 5: acessibilidade, lazy-load e indicador de atualização no index.html."""
from pathlib import Path

HTML = Path("docs/index.html").read_text(encoding="utf-8")
METH = Path("docs/como-lemos.html").read_text(encoding="utf-8")


def test_focus_visible_and_skip_styles():
    assert ":focus-visible" in HTML
    assert "a:focus,button:focus,select:focus" in HTML
    assert ".sr-only" in HTML


def test_aria_on_interactive_controls():
    assert 'aria-expanded="false"' in HTML
    assert "aria-controls=\"cmp-" in HTML
    assert 'role="button" tabindex="0"' in HTML
    assert "aria-label=\"Filtrar por editoria\"" in HTML
    assert "aria-label=\"Filtrar por veículo\"" in HTML
    assert 'role="status" aria-live="polite"' in HTML


def test_heading_hierarchy_has_hidden_h2_in_hero():
    assert 'id="heroTitle" class="sr-only"' in HTML
    assert "<h2 id=\"heroTitle\"" in HTML


def test_images_lazy_and_alt():
    # todas as imagens geradas no JS usam loading="lazy" e alt
    assert HTML.count('loading="lazy"') >= 3
    assert 'alt="" loading="lazy"' in HTML


def test_update_indicator_and_poll():
    assert 'id="updLine"' in HTML
    assert "checkNewEdition" in HTML
    assert "setInterval(checkNewEdition" in HTML
    assert 'id="newEdBtn"' in HTML


def test_meta_description_present():
    assert '<meta name="description"' in HTML


def test_mobile_has_no_min_width_overflow():
    """Item 4 do backlog: grid e cabeçalho não podem forçar largura mínima."""
    assert "grid-template-columns:minmax(0,1fr)" in HTML
    assert "#feedCol,#feed,.story" in HTML
    assert "#ed,#src{max-width:100%" in HTML


def test_sort_control_and_hero_bias_legend():
    """Itens 1a e 2 do backlog: legenda nos destaques e ordenação."""
    assert 'class="sortctl"' in HTML
    assert 'data-sort="chrono"' in HTML and 'data-sort="highlight"' in HTML
    assert "function orderList(" in HTML
    assert "recent.n_6h" in HTML
    assert "biasLegend(s, 'mini')" in HTML
    assert ".biaslegend.mini" in HTML


def test_pauta_links_and_feed_filter():
    """P2: pauta de capa abre 'veja também' e filtra o feed."""
    assert 'class="pauta-link"' in HTML
    assert 'data-pauta="' in HTML
    assert "function setPauta(" in HTML
    assert "Veja também nesta pauta" in HTML
    assert '<details class="pauta">' in HTML
    assert "pauta_key===S.pauta" in HTML
    assert 'class="pauta-banner"' in HTML
    assert "× Sair da pauta" in HTML
    assert ".pauta-banner .pb-srcs{display:flex;flex-wrap:wrap" in HTML


def test_pauta_banner_shows_aggregate_bias():
    """P3: a pauta mostra a barra somada, não só a da história isolada."""
    assert "Viés da pauta" in HTML
    assert '${biasBar(p)}' in HTML
    assert "Blindspot da pauta" in HTML
    assert ".pauta-banner .pb-bias{" in HTML


def test_pauta_call_shows_latest_front_headline():
    """Chamada da pauta = manchete de capa mais recente, com subtítulo."""
    assert "function callOf(" in HTML
    assert "p.call || {}" in HTML
    assert "pb-sum" in HTML
    assert "call.summary" in HTML
    assert "s.pauta_key||s.topic||s.id" in HTML


def test_pauta_on_the_fly_fallback():
    """Pauta nova sem conceito não pode sumir do topo (fase 0)."""
    assert "bestOther" in HTML
    assert "!s.pauta_key" in HTML


def test_pauta_aliases_resolve_old_links():
    assert "pautas_aliases" in HTML
    assert "(S.data.pautas_aliases||{})[key]" in HTML


def test_opiniao_section_one_card_per_side():
    """Item 3: opinião E/C/D, rotulada como opinião e não cobertura."""
    assert 'id="opiniaoSec"' in HTML
    assert "function renderOpiniao(" in HTML
    assert "opinião, não cobertura" in HTML
    assert 'href="#opiniaoSec"' in HTML
    assert ".opgrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))" in HTML
    assert "@media(max-width:720px){.opgrid{grid-template-columns:1fr}}" in HTML
    assert "opauthor" in HTML
    assert "border-top-color" in HTML
    assert "['L','Esquerda']" not in HTML


def test_metrics_card_and_series():
    """Item 5: série simples de métricas e pautas no site."""
    assert 'id="metricsCard"' in HTML
    assert "function renderMetrics(" in HTML
    assert "A semana em números" in HTML
    assert "unmatched_rate" in HTML
    assert "n_emergent" in HTML
    assert ".mrow{display:grid" in HTML


def test_chronology_shows_publication_and_update():
    assert "function timeLabel(" in HTML
    assert "publicada ${relTime" in HTML
    assert "first_published" in HTML


def test_hero_side_aligns_image_top_and_biasrow_bottom():
    assert "topAnchor.getBoundingClientRect().top" in HTML
    assert "bias.getBoundingClientRect().bottom" in HTML
    assert "side.style.marginTop" in HTML
    assert "bias.getBoundingClientRect().bottom - top" in HTML


def test_metodologia_atribui_vies_e_factualidade_a_tres_ias():
    assert "três modelos de IA diferentes" in METH
    assert "mediana das três leituras" in METH
    assert "curadoria manual" not in METH.lower()
    assert "revisão humana" not in METH.lower()
    assert "Factualidade" in METH and "revisão por IA" in METH


def test_framing_category_removed():
    assert "Como cada lado intitulou" not in HTML
    assert "function framingHTML(" not in HTML
