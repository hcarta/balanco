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
        _art("d", "Governo anuncia medidas econômicas para o mês",
             "https://d/1"),
    ]
    groups = app.build_opiniao(arts, _meta(), now=now, path=str(path))
    assert [len(groups[k]) for k in ("L", "C", "R")] == [1, 1, 1]
    assert groups["L"][0]["source"] == "Fonte E"      # factualidade maior
    assert groups["C"][0]["source"] == "Fonte B"
    assert groups["R"][0]["source"] == "Fonte C"
    assert len({groups[k][0]["source"] for k in ("L", "C", "R")}) == 3

    # mesma janela: seleção persistida, mesmo sem artigos novos
    again = app.build_opiniao([], _meta(), now=now, path=str(path))
    assert again == groups

    # próxima janela (18h): recalcula; sem artigos, fica vazio
    later = datetime(2026, 11, 2, 19, 0, tzinfo=timezone.utc)
    empty = app.build_opiniao([], _meta(), now=later, path=str(path))
    assert empty == {"L": [], "C": [], "R": []}


def test_build_opiniao_ignores_non_opinion_and_old_pieces(tmp_path):
    now = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)
    path = tmp_path / "opiniao.json"
    old = _art("a", "Opinião: texto antigo sobre a economia", "https://a/9")
    old["published"] = "2026-10-30T10:00:00+00:00"
    hard = _art("b", "Governo anuncia pacote de medidas", "https://b/9")
    hard["section"] = "política"
    arts = [old, hard]
    groups = app.build_opiniao(arts, _meta(), now=now, path=str(path))
    assert groups == {"L": [], "C": [], "R": []}
