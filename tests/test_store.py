"""Cache SQLite: dedup, janela temporal, headers condicionais."""
import time

from store import Store


def make_store(tmp_path):
    return Store(path=str(tmp_path / "cache.db"))


def test_upsert_dedups_by_link(tmp_path):
    s = make_store(tmp_path)
    items = [
        {"title": "A", "link": "https://x/1", "summary": "", "published": "2026-10-30T00:00:00+00:00",
         "ts": time.time(), "section": "", "image": ""},
        {"title": "B", "link": "https://x/2", "summary": "", "published": "2026-10-30T00:00:00+00:00",
         "ts": time.time(), "section": "", "image": ""},
    ]
    assert s.upsert_articles("g1", items) == 2
    assert s.upsert_articles("g1", items) == 0  # nada novo
    s.close()


def test_recent_respects_window(tmp_path):
    s = make_store(tmp_path)
    now = time.time()
    s.upsert_articles("g1", [
        {"title": "Nova", "link": "https://x/nova", "summary": "",
         "published": "2026-10-30T00:00:00+00:00", "ts": now, "section": "", "image": ""},
        {"title": "Velha", "link": "https://x/velha", "summary": "",
         "published": "2026-10-01T00:00:00+00:00", "ts": now - 30 * 86400,
         "section": "", "image": ""},
    ])
    got = s.recent("g1", window_h=72)
    assert [a["title"] for a in got] == ["Nova"]
    s.close()


def test_cond_headers_roundtrip(tmp_path):
    s = make_store(tmp_path)
    assert s.cond_headers("https://x/feed") == {}
    s.save_http("https://x/feed", '"abc"', "Thu, 30 Oct 2026 00:00:00 GMT")
    h = s.cond_headers("https://x/feed")
    assert h == {"If-None-Match": '"abc"', "If-Modified-Since": "Thu, 30 Oct 2026 00:00:00 GMT"}
    s.close()


def test_count_recent_and_window_in_health(tmp_path):
    s = make_store(tmp_path)
    now = time.time()
    s.upsert_articles("g1", [
        {"title": f"Nova {i}", "link": f"https://x/{i}", "summary": "",
         "published": "2026-10-31T00:00:00+00:00", "ts": now,
         "section": "", "image": ""} for i in range(3)
    ])
    s.upsert_articles("g1", [
        {"title": "Velha", "link": "https://x/velha", "summary": "",
         "published": "2026-10-01T00:00:00+00:00", "ts": now - 30 * 86400,
         "section": "", "image": ""}
    ])
    assert s.count_recent("g1", window_h=72) == 3
    assert len(s.recent("g1", window_h=72, limit=2)) == 2  # cap
    s.log_fetch("g1", "2026-10-31T12:00:00+00:00", 3, 2, "ok", 10,
                n_window=3)
    h = s.health()["g1"]
    assert h["last_n_window"] == 3
    assert h["last_n_total"] == 2
    s.close()


def _story(sid, links, title="História"):
    return {"id": sid, "title": title,
            "articles": [{"link": l, "first_seen": "2026-10-31T10:00:00+00:00",
                          "source": "Fonte"} for l in links],
            "aliases": []}


def test_sync_stories_persists_members_and_events(tmp_path):
    s = make_store(tmp_path)
    s.sync_stories([_story("h1", ["l1", "l2"])], "2026-10-31T12:00:00+00:00")
    assert s.db.execute("SELECT COUNT(*) FROM stories").fetchone()[0] == 1
    assert s.db.execute("SELECT COUNT(*) FROM story_members").fetchone()[0] == 2
    kinds = [r[0] for r in s.db.execute("SELECT kind FROM story_events")]
    assert "new_member" in kinds
    s.sync_stories([_story("h1", ["l1", "l2", "l3"])],
                   "2026-10-31T12:30:00+00:00")
    assert s.db.execute("SELECT COUNT(*) FROM story_members").fetchone()[0] == 3
    s.close()


def test_sync_stories_aliases_and_split(tmp_path):
    s = make_store(tmp_path)
    s.sync_stories([_story("h1", ["l1", "l2"])], "2026-10-31T12:00:00+00:00")
    # l1/l2 migram para h2 (novo id)
    s.sync_stories([_story("h2", ["l1", "l2"])], "2026-10-31T12:30:00+00:00")
    aliases = s.aliases_map()
    assert aliases.get("h2") == ["h1"]
    kinds = [r[0] for r in s.db.execute("SELECT kind FROM story_events")]
    assert "merge" in kinds or "split" in kinds
    s.close()
