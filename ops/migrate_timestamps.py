#!/usr/bin/env python3
"""F-02: corrige o deslocamento de +3 h nas datas de feeds RSS.

O bug antigo (`time.mktime`) interpretava o struct UTC como hora local e
somava o offset do runner. As fontes de sitemap não foram afetadas (parseiam
ISO com offset). Este script:

1. detecta, por fonte, o deslocamento máximo entre `ts` e `first_seen`;
2. se for >= 1 h, subtrai esse offset de TODAS as linhas daquela fonte;
3. reescreve `published` a partir do `ts` corrigido.

É idempotente: depois da correção o deslocamento máximo fica ~0 e o script
não mexe mais. Use `--dry-run` para inspecionar.

Uso: python ops/migrate_timestamps.py [--dry-run]
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import yaml  # noqa: E402

DB = os.path.join(BASE, "state", "cache.db")


def _first_seen_ts(value: str) -> float | None:
    try:
        return datetime.fromisoformat(value).timestamp()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(os.path.join(BASE, "sources.yaml"), encoding="utf-8") as f:
        sources = yaml.safe_load(f)["sources"]
    rss_ids = {s["id"] for s in sources if s.get("rss")}

    db = sqlite3.connect(DB)
    changed = 0
    per_source = {}
    for sid in rss_ids:
        rows = db.execute(
            "SELECT link, ts, first_seen FROM articles WHERE source_id=?",
            (sid,)).fetchall()
        shifts = []
        for _, ts, fs in rows:
            f = _first_seen_ts(fs)
            if f is not None:
                shifts.append((ts - f) / 3600)
        if shifts:
            per_source[sid] = (rows, max(shifts))
    if not per_source:
        print("nada a migrar.")
        return
    # O offset é o mesmo para todas as fontes RSS (fuso do runner). Usar o
    # máximo global evita subtrair 2 h de uma fonte cujo item mais recente
    # foi publicado há mais de 1 h.
    global_max = max(v[1] for v in per_source.values())
    offset = int(round(global_max)) * 3600
    print(f"offset global detectado: {global_max:.2f} h -> {offset // 3600} h")
    for sid in sorted(per_source):
        rows, max_shift = per_source[sid]
        if max_shift < 1.0:
            continue
        print(f"{sid:14} {len(rows):4d} linhas; deslocamento {max_shift:.2f} h")
        if args.dry_run:
            continue
        for link, ts, _ in rows:
            new_ts = ts - offset
            new_pub = datetime.fromtimestamp(new_ts, tz=timezone.utc).isoformat()
            db.execute("UPDATE articles SET ts=?, published=? WHERE link=?",
                       (new_ts, new_pub, link))
            changed += 1
    if not args.dry_run:
        db.commit()
        print(f"\n{changed} artigos corrigidos.")
    db.close()


if __name__ == "__main__":
    main()
