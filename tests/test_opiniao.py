"""Item 3 do backlog: opinião E/C/D, 1 por lado, estável por janela."""
from datetime import datetime, timezone

import app


def _meta():
    return {
        "a": {"id": "a", "name": "Fonte A", "bias": -1.5, "factuality": "high"},
        "e": {"id": "e", "name": "Fonte E", "bias": -1.2, "factuality": "very_high"},
        "b": {"id": "b", "name": "Fonte B", "bias": 0.0, "factuality": "very_high"},
        "c": {"id": "c", "name": "Fonte C", "bias": 1.4, "factuality": "high"},
        "d": {"id": "d", "name": "Fonte D", "bias": 1.1, "factuality": "mixed"},
        "f": {"id": "f", "name": "Fonte F", "bias": 0.8, "factuality": "high"},
        "g": {"id": "g", "name": "Fonte G", "bias": 1.8, "factuality": "very_high"},
    }


def _art(sid, title, link):
    return {"source_id": sid, "title": title, "link": link,
            "published": "2026-11-02T11:00:00+00:00", "section": "opiniao"}


def test_build_opiniao_one_per_side_and_stable_window(tmp_path):
    now = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)
    path = tmp_path / "opiniao.json"
    arts = [
        _art("a", "Opinião: a economia e o rumo do país", "https://a/1"),
        _art("e", "Opinião: o custo da dívida pública", "https://e/1"),
        _art("b", "Opinião: o centro e a reforma possível", "https://b/1"),
        _art("c", "Opinião: a liberdade econômica em debate", "https://c/1"),
        _art("f", "Opinião: o mercado e as regras do jogo", "https://f/1"),
        _art("g", "Opinião: o peso do Estado na economia", "https://g/1"),
        _art("d", "Governo anuncia medidas econômicas para o mês",
             "https://d/1"),
    ]
    out = app.build_opiniao(arts, _meta(), now=now, path=str(path),
                            fetch_missing=False)
    items = out["items"]
    assert len(items) == 5
    assert len({x["source"] for x in items}) == 5
    assert it_side_counts(items)["L"] <= 2 and it_side_counts(items)["R"] <= 2
    assert "Fonte D" not in {x["source"] for x in items}   # não é opinião

    # mesma janela: seleção persistida, mesmo sem artigos novos
    again = app.build_opiniao([], _meta(), now=now, path=str(path),
                              fetch_missing=False)
    assert again["items"] == items

    # próxima janela (18h): recalcula; sem artigos, fica vazio
    later = datetime(2026, 11, 2, 19, 0, tzinfo=timezone.utc)
    empty = app.build_opiniao([], _meta(), now=later, path=str(path),
                              fetch_missing=False)
    assert empty["items"] == []


def test_build_opiniao_ignores_non_opinion_and_old_pieces(tmp_path):
    now = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)
    path = tmp_path / "opiniao.json"
    old = _art("a", "Opinião: texto antigo sobre a economia", "https://a/9")
    old["published"] = "2026-10-30T10:00:00+00:00"
    hard = _art("b", "Governo anuncia pacote de medidas", "https://b/9")
    hard["section"] = "política"
    arts = [old, hard]
    out = app.build_opiniao(arts, _meta(), now=now, path=str(path),
                            fetch_missing=False)
    assert out["items"] == []


def it_side_counts(items):
    out = {"L": 0, "C": 0, "R": 0}
    for x in items:
        out[x["side"]] = out.get(x["side"], 0) + 1
    return out


def test_opinion_author_from_blog_slug(tmp_path):
    now = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)
    art = {"source_id": "a",
           "title": "Vem aí a Universidade Social Portela, que inclui curso",
           "link": "https://oglobo.globo.com/blogs/ancelmo-gois/post/2026/11/x",
           "published": "2026-11-02T11:00:00+00:00", "section": "colunas"}
    out = app.build_opiniao([art], _meta(), now=now,
                            path=str(tmp_path / "o.json"), fetch_missing=False)
    assert out["items"][0]["author"] == "Ancelmo Gois"
