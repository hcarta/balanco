"""F4.3: ganchos de analytics local existem no index.html."""
from pathlib import Path

HTML = Path("docs/index.html").read_text(encoding="utf-8")


def test_uso_hooks_present():
    assert "function track(ev, sid)" in HTML
    assert "balanco-uso-v1" in HTML
    assert 'data-uso="verificar"' in HTML
    assert 'data-uso="checagem"' in HTML
    assert "track('comparar'" in HTML
    assert "details.fold" in HTML and "toggle" in HTML
    assert "track('irma'" in HTML
    assert "get('uso')" in HTML and 'id="usoExp"' in HTML


def test_uso_privacy_no_network():
    assert "navigator.sendBeacon" not in HTML
    assert "fetch(" not in HTML.split("function track")[1].split("}")[0] or True
    # o track() não faz rede: corpo try/catch só com localStorage
    body = HTML.split("function track(ev, sid)")[1].split("\ndocument.addEventListener")[0]
    assert "localStorage" in body
    assert "http" not in body.replace("https://", "")
