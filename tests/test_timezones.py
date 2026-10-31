"""F-02: datas de feed são UTC, não hora local.

O bug original (`time.mktime`) somava o offset do runner e jogava itens ~3 h
no futuro. Estes testes rodam a mesma fixture em dois fusos e exigem o mesmo
`ts`/`published`.
"""
import os
import time
from datetime import datetime, timezone

import collectors
import factcheck

RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Notícia de teste</title>
<link>https://exemplo/1</link>
<description>resumo</description>
<pubDate>Thu, 30 Oct 2026 12:00:00 GMT</pubDate></item>
</channel></rss>""".encode("utf-8")

EXPECTED_TS = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc).timestamp()
EXPECTED_ISO = "2026-10-30T12:00:00+00:00"


def _with_tz(tz, fn):
    old = os.environ.get("TZ")
    os.environ["TZ"] = tz
    time.tzset()
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def _rss(monkeypatch):
    monkeypatch.setattr(collectors, "_http",
                        lambda *a, **k: (RSS, 200, None, None, 0))
    items, _ = collectors.fetch_rss({"id": "x", "name": "X",
                                     "rss": "https://exemplo/feed"},
                                    limit=10)
    return items[0]


def test_fetch_rss_is_utc_in_any_timezone(monkeypatch):
    utc = _with_tz("UTC", lambda: _rss(monkeypatch))
    local = _with_tz("America/Sao_Paulo", lambda: _rss(monkeypatch))
    assert utc["ts"] == local["ts"] == EXPECTED_TS
    assert utc["published"] == local["published"] == EXPECTED_ISO


def test_fetch_aosfatos_is_utc_in_any_timezone(monkeypatch):
    class R:
        status_code = 200
        content = RSS

        def raise_for_status(self):
            pass

    monkeypatch.setattr(factcheck.requests, "get", lambda *a, **k: R())

    def run():
        return factcheck.fetch_aosfatos()[0]

    utc = _with_tz("UTC", run)
    local = _with_tz("America/Sao_Paulo", run)
    assert utc["published"] == local["published"] == EXPECTED_ISO
