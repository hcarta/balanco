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
