"""C-1: índice de leituras da semana (janela própria, sem matching)."""
import pytest

import app


@pytest.fixture(autouse=True)
def _no_piaui_home(monkeypatch):
    """Testes não batem na home da piauí (a rede falha e a função devolve None)."""
    def boom(*a, **k):
        raise RuntimeError("sem rede no teste")
    monkeypatch.setattr("requests.get", boom)

SOURCES = [
    {"id": "piaui", "name": "piauí", "longform": True, "bias": -1.0},
    {"id": "nexo", "name": "Nexo", "longform": True, "bias": 0.0},
    {"id": "g1", "name": "G1", "longform": False, "bias": 0.0},
]


class FakeStore:
    def __init__(self, data):
        self.data = data

    def recent(self, source_id, window_h=72, limit=900):
        return self.data.get(source_id, [])[:limit]


def art(title, link, published, summary="resumo"):
    return {"title": title, "link": link, "published": published,
            "summary": summary, "section": "", "ts": 0}


def test_build_leituras_filters_and_diversifies():
    store = FakeStore({
        "piaui": [
            art("O instituto de Mendonça", "p1", "2026-10-31T10:00:00+00:00"),
            art("O esgrimista", "p2", "2026-10-30T10:00:00+00:00"),
            art("Palavras cruzadas", "p3", "2026-10-29T10:00:00+00:00"),
            art("Sem resumo", "p4", "2026-10-28T10:00:00+00:00", summary="None"),
            art("Respostas enviados para reportagem sobre investimentos", "p5",
                "2026-10-27T10:00:00+00:00"),
        ],
        "nexo": [
            art("Como funciona o Congresso", "n1", "2026-10-31T09:00:00+00:00",
                summary="<p>Texto <b>limpo</b> &amp; útil</p>"),
            art("O que muda com a PEC", "n2", "2026-10-30T09:00:00+00:00"),
            art("Duplicada de outra fonte", "p1", "2026-10-29T09:00:00+00:00"),
        ],
        "g1": [art("Notícia comum", "g1", "2026-10-31T11:00:00+00:00")],
    })
    out = app.build_leituras(store, SOURCES, days=10, limit=8,
                             exclude_links={"p2"})
    links = [x["link"] for x in out]
    assert "p1" in links and "p2" not in links
    assert "p3" not in links and "p4" not in links and "p5" not in links
    assert "g1" not in links
    assert len([x for x in out if x["source_id"] == "piaui"]) <= 2
    assert [x["link"] for x in out] == ["p1", "n1", "n2"]
    assert out[1]["summary"] == "Texto limpo & útil"


def test_build_leituras_without_store_is_empty():
    assert app.build_leituras(None, SOURCES) == []


def test_build_leituras_excludes_foro_de_teresina():
    """F-08: /web/ftNNN/ (Foro de Teresina, podcast) não entra nem com dek."""
    store = FakeStore({
        "piaui": [
            art("Vitória da democracia: Lula faz história",
                "https://piaui.uol.com.br/web/ft136/",
                "2026-10-30T13:06:54+00:00",
                summary="Episódio com análise da semana"),
            art("O instituto de Mendonça",
                "https://piaui.uol.com.br/web/andre-mendonca-instituto-iter/",
                "2026-10-27T09:00:00+00:00"),
        ],
    })
    out = app.build_leituras(store, SOURCES, days=10, limit=8)
    assert [x["link"] for x in out] == [
        "https://piaui.uol.com.br/web/andre-mendonca-instituto-iter/"]


def test_build_leituras_keeps_two_piaui():
    """Item 8: piauí sempre com 2 leituras (destaque + tema da semana)."""
    store = FakeStore({
        "piaui": [art(f"Peça piauí {i}", f"p{i}",
                      f"2026-10-3{i}T10:00:00+00:00") for i in range(3)],
        "nexo": [art(f"Nexo {i}", f"n{i}",
                     f"2026-10-3{i}T09:00:00+00:00") for i in range(3)],
    })
    stories = [{"title": "Peça piauí 1 e o caso Master no STF", "articles": []}]
    out = app.build_leituras(store, SOURCES, days=10, limit=6, stories=stories)
    assert sum(1 for x in out if x["source_id"] == "piaui") >= 2


def test_leituras_ad_filter():
    assert app.LEITURAS_AD.search("Publi de graça no Núcleo – veja como")
    assert app.LEITURAS_AD.search("Conteúdo patrocinado: novo banco digital")
    assert not app.LEITURAS_AD.search("A grande muralha de posts")


def test_piaui_featured_parses_image(monkeypatch):
    html = ('<section class="tema-escuro destaque1a"><a href="/revista/241/x/" '
            'class="destaque1a-img"><img src="/media/x.jpg"></a>'
            '<a href="/revista/241/x/"><h1>A proteína polêmica</h1></a>'
            '<p class="linha-fina-grande">dek</p></section>')

    class R:
        text = html

    monkeypatch.setattr("requests.get", lambda *a, **k: R())
    feat = app._piaui_featured()
    assert feat["title"] == "A proteína polêmica"
    assert feat["image"] == "https://piaui.uol.com.br/media/x.jpg"
