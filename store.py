"""
Cache SQLite incremental + HTTP condicional (Fase 1.1 / 1.2).

- `articles`: todo artigo já visto (dedup por link canônico), com first_seen.
- `http_state`: ETag / Last-Modified por URL (para If-None-Match / If-Modified-Since).
- `fetches`: uma linha por fonte por rodada (itens novos, totais, status, latência).
- `runs`: resumo de cada rodada.

Com cache quente, a rodada lê o que já tem no banco e só baixa o que mudou
(ou recebe 304 e não baixa nada).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE, "state", "cache.db")

RECENT_WINDOW_H = 72
PER_SOURCE_CAP = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles(
  link TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT DEFAULT '',
  published TEXT NOT NULL,
  ts REAL NOT NULL,
  section TEXT DEFAULT '',
  image TEXT DEFAULT '',
  first_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_articles_src_ts ON articles(source_id, ts DESC);
CREATE TABLE IF NOT EXISTS http_state(
  url TEXT PRIMARY KEY,
  etag TEXT,
  last_modified TEXT,
  updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fetches(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  run_ts TEXT NOT NULL,
  n_fresh INTEGER DEFAULT 0,
  n_total INTEGER DEFAULT 0,
  status TEXT NOT NULL,
  ms INTEGER DEFAULT 0,
  note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_fetches_src ON fetches(source_id, id DESC);
CREATE TABLE IF NOT EXISTS runs(
  run_ts TEXT PRIMARY KEY,
  n_ok INTEGER DEFAULT 0,
  n_err INTEGER DEFAULT 0,
  n_new INTEGER DEFAULT 0,
  n_total INTEGER DEFAULT 0,
  ms INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bodies(
  url TEXT PRIMARY KEY,
  meta TEXT DEFAULT '',
  body TEXT DEFAULT '',
  paywalled INTEGER DEFAULT 0,
  method TEXT DEFAULT '',
  fetched TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str = DEFAULT_DB):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(SCHEMA)

    # ── HTTP condicional ──
    def cond_headers(self, url: str) -> dict:
        row = self.db.execute(
            "SELECT etag, last_modified FROM http_state WHERE url=?", (url,)
        ).fetchone()
        h = {}
        if row:
            if row[0]:
                h["If-None-Match"] = row[0]
            if row[1]:
                h["If-Modified-Since"] = row[1]
        return h

    def save_http(self, url: str, etag: str | None, last_modified: str | None):
        self.db.execute(
            "INSERT INTO http_state(url, etag, last_modified, updated)"
            " VALUES(?,?,?,?)"
            " ON CONFLICT(url) DO UPDATE SET etag=excluded.etag,"
            " last_modified=excluded.last_modified, updated=excluded.updated",
            (url, etag, last_modified, _now_iso()),
        )
        self.db.commit()

    # ── artigos ──
    def upsert_articles(self, source_id: str, items: list[dict]) -> int:
        """Insere ignorando links já vistos. Retorna quantos são novos."""
        if not items:
            return 0
        now = _now_iso()
        before = self.db.total_changes
        self.db.executemany(
            "INSERT OR IGNORE INTO articles"
            "(link, source_id, title, summary, published, ts, section, image, first_seen)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            [(a["link"], source_id, a.get("title", ""), a.get("summary", ""),
              a.get("published", now), float(a.get("ts", 0)),
              a.get("section", ""), a.get("image", ""), now)
             for a in items if a.get("link")],
        )
        new = self.db.total_changes - before
        # backfill: imagem que faltava + seção recalculada (cura valores antigos).
        # Imagem nunca é apagada; seção é atualizada quando a nova difere.
        self.db.executemany(
            "UPDATE articles SET image=COALESCE(NULLIF(? ,''), image), section=?"
            " WHERE link=? AND ((image IS NULL OR image='') OR section != ?)",
            [(a.get("image", ""), a.get("section", ""), a["link"], a.get("section", ""))
             for a in items if a.get("link") and (a.get("image") or a.get("section"))])
        self.db.commit()
        return new

    def recent(self, source_id: str, window_h: float = RECENT_WINDOW_H,
               limit: int = PER_SOURCE_CAP) -> list[dict]:
        cutoff = datetime.now(timezone.utc).timestamp() - window_h * 3600
        rows = self.db.execute(
            "SELECT title, link, summary, published, ts, section, image"
            " FROM articles WHERE source_id=? AND ts>? ORDER BY ts DESC LIMIT ?",
            (source_id, cutoff, limit),
        ).fetchall()
        return [{"title": r[0], "link": r[1], "summary": r[2] or "",
                 "published": r[3], "ts": r[4], "section": r[5] or "",
                 "image": r[6] or ""} for r in rows]

    # ── rodadas e saúde ──
    def log_fetch(self, source_id: str, run_ts: str, n_fresh: int,
                  n_total: int, status: str, ms: int, note: str = ""):
        self.db.execute(
            "INSERT INTO fetches(source_id, run_ts, n_fresh, n_total, status, ms, note)"
            " VALUES(?,?,?,?,?,?,?)",
            (source_id, run_ts, n_fresh, n_total, status, ms, note[:300]),
        )
        self.db.commit()

    def log_run(self, run_ts: str, n_ok: int, n_err: int,
                n_new: int, n_total: int, ms: int):
        self.db.execute(
            "INSERT OR REPLACE INTO runs(run_ts, n_ok, n_err, n_new, n_total, ms)"
            " VALUES(?,?,?,?,?,?)",
            (run_ts, n_ok, n_err, n_new, n_total, ms),
        )
        self.db.commit()

    # ── corpos (Fase 3.1, TTL 7 dias) ──
    def get_body(self, url: str, ttl_days: float = 7) -> dict | None:
        row = self.db.execute(
            "SELECT meta, body, paywalled, method, fetched FROM bodies WHERE url=?",
            (url,)).fetchone()
        if not row:
            return None
        try:
            age = (datetime.now(timezone.utc) -
                   datetime.fromisoformat(row[4])).total_seconds() / 86400
        except Exception:
            age = 999
        if age > ttl_days:
            return None
        return {"meta": row[0], "body": row[1],
                "paywalled": bool(row[2]), "method": row[3]}

    def save_body(self, url: str, result: dict):
        self.db.execute(
            "INSERT INTO bodies(url, meta, body, paywalled, method, fetched)"
            " VALUES(?,?,?,?,?,?)"
            " ON CONFLICT(url) DO UPDATE SET meta=excluded.meta, body=excluded.body,"
            " paywalled=excluded.paywalled, method=excluded.method, fetched=excluded.fetched",
            (url, result.get("meta", ""), result.get("body", ""),
             1 if result.get("paywalled") else 0, result.get("method", ""),
             _now_iso()))
        self.db.commit()

    def health(self) -> dict:
        """Último estado por fonte + sequências de erro/zeradas."""
        out = {}
        srcs = [r[0] for r in self.db.execute(
            "SELECT DISTINCT source_id FROM fetches").fetchall()]
        for s in srcs:
            rows = self.db.execute(
                "SELECT run_ts, n_fresh, n_total, status, ms FROM fetches"
                " WHERE source_id=? ORDER BY id DESC LIMIT 5", (s,)).fetchall()
            if not rows:
                continue
            err_streak = 0
            for r in rows:
                if r[3] == "error":
                    err_streak += 1
                else:
                    break
            out[s] = {
                "last_run": rows[0][0],
                "last_n_fresh": rows[0][1],
                "last_n_total": rows[0][2],
                "last_status": rows[0][3],
                "last_ms": rows[0][4],
                "err_streak": err_streak,
                "empty": rows[0][2] == 0,
            }
        return out

    def alerts(self) -> list[str]:
        msgs = []
        for sid, h in self.health().items():
            if h["err_streak"] >= 2:
                msgs.append(f"{sid}: ERRO {h['err_streak']} rodadas seguidas")
            elif h["empty"]:
                msgs.append(f"{sid}: 0 artigos (última rodada {h['last_run'][:16]})")
        return msgs

    def close(self):
        self.db.close()
