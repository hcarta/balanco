"""Backlog item 5: métricas diárias, week_digest e acompanhamento de pautas."""
import gzip
import json
from datetime import datetime, timezone

import digest

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def _story(sid, total, ind, pct=None, blind=None, longreads=0):
    return {"id": sid, "title": f"História {sid} sobre economia e política",
            "counts": {"total": total, "independent": ind,
                       "groups": {}, "frames": 0, "articles": total},
            "pct": pct or {"L": 20, "CL": 0, "C": 40, "CR": 20, "R": 20},
            "blindspot": blind, "longreads": [{"link": "https://x"}] * longreads,
            "articles": [{"link": f"https://{sid}", "title": f"Matéria {sid}"}],
            "summary": "Resumo da história para o digest.",
            "updated": "2026-11-02T10:00:00+00:00"}


def test_story_metrics_median_and_percentages():
    stories = [_story("a", 10, 4, blind="left", longreads=1),
               _story("b", 6, 2),
               _story("c", 8, 6)]
    m = digest.story_metrics(stories)
    assert m["n_stories"] == 3
    assert m["median_independent"] == 4
    assert m["pct_blindspot"] == 33.3
    assert m["pct_longread"] == 33.3
    assert m["avg_pct"]["C"] == 40.0


def test_update_metrics_overwrites_same_day_and_series(tmp_path):
    base = str(tmp_path / "metrics")
    a = digest.update_metrics([_story("a", 10, 4)], base=base, now=NOW)
    assert a["week"] == "2026-W45"
    b = digest.update_metrics([_story("a", 10, 4), _story("b", 6, 2)],
                              base=base, now=NOW)
    assert len(b["series"]) == 1                 # um dia só
    assert b["series"][0]["n_stories"] == 2      # última rodada vence
    later = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    c = digest.update_metrics([_story("c", 5, 3)], base=base, now=later)
    assert len(c["series"]) == 2
    assert [x["date"] for x in c["series"]] == ["2026-11-02", "2026-11-03"]


def test_week_digest_is_readable_and_slim(tmp_path):
    path = str(tmp_path / "week.json.gz")
    n = digest.build_week_digest([_story("a", 10, 4, blind="left")],
                                 path=path, now=NOW)
    assert n == 1
    with gzip.open(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    s = data["stories"][0]
    assert s["auto"] is True
    assert s["auto_summary"].startswith("Resumo da história")
    assert s["counts"]["groups"] == {"L": 0, "CL": 0, "C": 0, "CR": 0, "R": 0}
    assert s["blindspot"] == "left"
    assert "https://a" in s["links"]


def test_auto_summary_fallback_without_summary():
    s = _story("a", 10, 4)
    s["summary"] = ""
    out = digest.auto_summary(s)
    assert "10 coberturas" in out and "4 grupos" in out


def test_pautas_metrics_series(tmp_path):
    path = str(tmp_path / "pautas.json")
    a = digest.update_pautas_metrics({"n_pautas": 7, "unmatched_rate": 43.0,
                                      "n_emergent": 1}, path=path, now=NOW)
    assert a["today"]["date"] == "2026-11-02"
    later = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    b = digest.update_pautas_metrics({"n_pautas": 8, "unmatched_rate": 30.0,
                                      "n_emergent": 2}, path=path, now=later)
    assert len(b["series"]) == 2
    assert b["series"][-1]["n_emergent"] == 2
