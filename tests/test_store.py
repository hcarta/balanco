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
