"""Fase 5: acessibilidade, lazy-load e indicador de atualização no index.html."""
from pathlib import Path

HTML = Path("docs/index.html").read_text(encoding="utf-8")


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
