"""Vereditos de checagem a partir do título."""
import pytest

import factcheck
from factcheck import verdict_from_title


@pytest.mark.parametrize("title,expected", [
    ("É #FAKE que governo federal recuou sobre fim da escala 6x1", "falso"),
    ("É falso que Bolsonaro foi enviado de volta à Papuda", "falso"),
    ("Documento falso distorce dados do TSE", "falso"),
    ("É #FATO que vacina reduz internações, apontam estudos", "verdadeiro"),
    ("Veja o que é #FATO ou #FAKE no debate da Globo", "checagem"),
    ("Número de eleitores maior que o de habitantes não indica fraude", "enganoso"),
    ("Reportagem que mostra cortes não é atual; vídeo é de 2024", "enganoso"),
    ("Vídeo de professores em greve é de paralisação e não tem relação com corte", "enganoso"),
    ("Prefeitura anuncia novo parque na zona sul", "checagem"),
    # padrões do Aos Fatos
    ("Jair Bolsonaro não foi preso por desacato após resultado das eleições", "falso"),
    ("Vídeo que mostra Flávio chorando não foi gravado após derrota", "falso"),
    ("Vídeo antigo circula nas redes para sugerir que Flávio foi para os EUA", "enganoso"),
    ("Notícia sobre bloqueio de R$ 6 bilhões na Saúde é de julho de 2024", "enganoso"),
    ("Checamos Flávio Bolsonaro e Lula no debate da Globo", "checagem"),
])
def test_verdict_from_title(title, expected):
    assert verdict_from_title(title) == expected


def test_fetch_aosfatos_strips_suffix(monkeypatch):
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel>
    <item><title>Relat\xc3\xb3rio ap\xc3\xb3crifo distorce microdados do TSE - Aos Fatos</title>
    <link>https://news.google.com/rss/articles/XYZ</link>
    <pubDate>Thu, 30 Oct 2026 12:00:00 GMT</pubDate></item>
    </channel></rss>"""

    class R:
        status_code = 200
        content = rss
        def raise_for_status(self): pass
    monkeypatch.setattr(factcheck.requests, "get", lambda *a, **k: R())
    items = factcheck.fetch_aosfatos()
    assert len(items) == 1
    assert items[0]["title"] == "Relatório apócrifo distorce microdados do TSE"
    assert items[0]["checker"] == "Aos Fatos"
    assert items[0]["verdict"] == "falso"


def test_fetch_lupa_paginates(monkeypatch):
    calls = []

    class R:
        def __init__(self, payload):
            self._p = payload
        def raise_for_status(self): pass
        def json(self): return self._p

    def fake_get(url, params=None, **k):
        calls.append(params.get("page"))
        n = 100 if params.get("page", 1) < 3 else 1
        return R([{"id": params.get("page") * 1000 + i,
                   "date": "2026-10-30T10:00:00",
                   "link": f"https://x/{params.get('page')}/{i}",
                   "title": {"rendered": f"Cheque {i} é falso"},
                   "excerpt": {"rendered": ""}} for i in range(n)])
    monkeypatch.setattr(factcheck.requests, "get", fake_get)
    items = factcheck.fetch_lupa(limit=250)
    assert [c for c in calls] == [1, 2, 3]
    assert len(items) == 201
    assert all(i["checker"] == "Agência Lupa" for i in items)
