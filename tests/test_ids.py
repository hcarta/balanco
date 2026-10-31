"""F-03: ids de história estáveis + aliases para links antigos."""
import time

import app

SOURCES = [
    {"id": "a", "name": "Fonte A", "bias": 0, "factuality": "high",
     "ownership": "independente"},
    {"id": "b", "name": "Fonte B", "bias": 0, "factuality": "high",
     "ownership": "independente"},
]


def articles():
    now = time.time()
    base = {
        "summary": "", "ts": now, "published": "2026-10-31T12:00:00+00:00",
        "section": "politica", "image": "", "base_bias": 0.0,
    }
    return [
        {**base, "title": "Senado aprova marco fiscal em votação apertada",
         "link": "https://exemplo/1", "source_id": "a", "source_name": "Fonte A",
         "first_seen": "2026-10-31T10:00:00+00:00"},
        {**base, "title": "Senado aprova marco fiscal em votação apertada no plenário",
         "link": "https://exemplo/2", "source_id": "b", "source_name": "Fonte B",
         "first_seen": "2026-10-31T10:05:00+00:00"},
    ]


def test_story_id_is_stable_under_order():
    a = app.build(SOURCES, articles(), {})
    b = app.build(SOURCES, list(reversed(articles())), {})
    assert len(a) == len(b) == 1
    assert a[0]["id"].startswith("h") and len(a[0]["id"]) == 9
    assert a[0]["id"] == b[0]["id"]


def test_assign_aliases_preserves_previous_id():
    stories = app.build(SOURCES, articles(), {})
    previous = [{"id": "s000", "articles": [
        {"link": "https://exemplo/1"}, {"link": "https://exemplo/2"}]}]
    app.assign_aliases(stories, previous)
    assert stories[0]["aliases"] == ["s000"]


def test_assign_aliases_ignores_unrelated_previous():
    stories = app.build(SOURCES, articles(), {})
    previous = [{"id": "s999", "articles": [{"link": "https://outro/9"}]}]
    app.assign_aliases(stories, previous)
    assert "aliases" not in stories[0]


def test_assign_aliases_inherits_legacy_aliases():
    stories = app.build(SOURCES, articles(), {})
    previous = [{"id": "hold123", "aliases": ["s000"], "articles": [
        {"link": "https://exemplo/1"}, {"link": "https://exemplo/2"}]}]
    app.assign_aliases(stories, previous)
    assert "s000" in stories[0]["aliases"]
    assert "hold123" in stories[0]["aliases"]
