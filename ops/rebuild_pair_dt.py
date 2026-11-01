"""Fase 0 (PLAN_FINAL): recalcula dt_h dos pares a partir do cache.

O bug: o audit F0/F1 gravou `ts` dos artigos com `app._ts_of()` (que lê
`updated`, campo de história) → 0 em todo artigo, logo `dt_h` = 0 em todos
os pares. Este script reaproveita os rótulos existentes e recomputa o Δt
real consultando `state/cache.db` por (source_id, título).

Uso:
    python ops/rebuild_pair_dt.py            # reescreve dt_h em cluster_pairs.jsonl
    python ops/rebuild_pair_dt.py --check    # só reporta
"""
import argparse
import json
import os
import sqlite3
import unicodedata


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAIRS = os.path.join(BASE, "tests", "cluster_pairs.jsonl")
CACHE = os.path.join(BASE, "state", "cache.db")


def norm(x):
    return unicodedata.normalize("NFKD", (x or "")).encode("ascii", "ignore") \
        .decode().lower().strip()


def load_cache():
    db = sqlite3.connect(CACHE)
    rows = db.execute(
        "SELECT source_id, title, ts, published, first_seen FROM articles"
    ).fetchall()
    db.close()
    by_key, by_title = {}, {}
    for sid, title, ts, pub, first in rows:
        try:
            t = float(ts) if ts else None
        except (TypeError, ValueError):
            t = None
        if t is None:
            continue
        by_key.setdefault((sid, norm(title)), t)
        by_title.setdefault(norm(title), t)
    return by_key, by_title


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    by_key, by_title = load_cache()
    recs = [json.loads(l) for l in open(PAIRS, encoding="utf-8") if l.strip()]

    found = miss = changed = 0
    for r in recs:
        ta = by_key.get((r.get("source_a"), norm(r["a"]))) \
            or by_title.get(norm(r["a"]))
        tb = by_key.get((r.get("source_b"), norm(r["b"]))) \
            or by_title.get(norm(r["b"]))
        if ta is None or tb is None:
            miss += 1
            continue
        found += 1
        dt = round(abs(ta - tb) / 3600, 2)
        if dt != r.get("dt_h"):
            changed += 1
        r["dt_h"] = dt

    dts = [r["dt_h"] for r in recs if r.get("dt_h")]
    nonzero = sum(1 for d in dts if d > 0)
    print(f"pares: {len(recs)} | com Δt real: {found} | sem par no cache: {miss}")
    print(f"dt_h != 0: {nonzero} | alterados: {changed}")
    if dts:
        s = sorted(dts)
        print(f"dt_h: min={s[0]} mediana={s[len(s)//2]} p90={s[int(len(s)*0.9)]} "
              f"max={s[-1]}")

    if args.check:
        return
    with open(PAIRS, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"→ {PAIRS} atualizado")


if __name__ == "__main__":
    main()
