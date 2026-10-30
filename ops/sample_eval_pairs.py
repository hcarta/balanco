#!/usr/bin/env python3
"""Amostra pares título×título estratificados para o conjunto de avaliação (Fase 2.1).

- 35 positivos: pares dentro do mesmo grupo do cluster() atual.
- 35 negativos difíceis: grupos diferentes, cosseno em [0.20, 0.45].
- 30 negativos fáceis: cosseno < 0.15.
Saída: tests/eval_pairs_unlabeled.jsonl (com palpite do algoritmo; rotular depois).
"""
import json
import os
import random
import sqlite3
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import app  # noqa: E402

N_POS, N_HARD, N_EASY = 35, 35, 30


def load_recent(window_h=72, cap=1200):
    db = sqlite3.connect(os.path.join(BASE, "state", "cache.db"))
    cutoff = time.time() - window_h * 3600
    rows = db.execute(
        "SELECT title, link, source_id FROM articles WHERE ts > ?"
        " ORDER BY ts DESC LIMIT ?", (cutoff, cap)).fetchall()
    db.close()
    return [{"title": r[0], "link": r[1], "source_id": r[2], "ts": time.time()} for r in rows]


def main():
    random.seed(42)
    arts = load_recent()
    print(f"{len(arts)} artigos recentes")
    X = app.tfidf_matrix([{"title": a["title"]} for a in arts])
    import numpy as np
    S = X @ X.T
    groups = app.cluster(arts)
    in_group = {}
    for g in groups:
        for i in g:
            in_group[i] = id(g)

    def same_group(i, j):
        return i in in_group and in_group.get(i) == in_group.get(j)

    n = len(arts)
    all_pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    pos = [(i, j) for i, j in all_pairs if same_group(i, j)]
    random.shuffle(pos)
    chosen_pos = pos[:N_POS]

    hard, easy = [], []
    for i, j in all_pairs:
        if same_group(i, j):
            continue
        c = float(S[i, j])
        shared = len(set(app.tok(arts[i]["title"])) & set(app.tok(arts[j]["title"])))
        if 0.20 <= c <= 0.45 and shared >= 2:
            hard.append((i, j, c, shared))
        elif c < 0.15:
            easy.append((i, j, c, shared))
    random.shuffle(hard)
    random.shuffle(easy)

    pairs = []
    for k, (i, j) in enumerate(chosen_pos):
        pairs.append(("pos", i, j, float(S[i, j]),
                      len(set(app.tok(arts[i]["title"])) & set(app.tok(arts[j]["title"]))), 1))
    for i, j, c, sh in hard[:N_HARD]:
        pairs.append(("hard", i, j, c, sh, 0))
    for i, j, c, sh in easy[:N_EASY]:
        pairs.append(("easy", i, j, c, sh, 0))

    out = os.path.join(BASE, "tests", "eval_pairs_unlabeled.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for k, (band, i, j, c, sh, pred) in enumerate(pairs):
            f.write(json.dumps({
                "id": f"P{k:03d}", "band": band,
                "a_title": arts[i]["title"], "a_source": arts[i]["source_id"],
                "b_title": arts[j]["title"], "b_source": arts[j]["source_id"],
                "cosine": round(c, 3), "shared": sh, "pred": pred,
            }, ensure_ascii=False) + "\n")
    print(f"{len(pairs)} pares → {out} "
          f"(pos={sum(1 for p in pairs if p[0]=='pos')}, "
          f"hard={sum(1 for p in pairs if p[0]=='hard')}, "
          f"easy={sum(1 for p in pairs if p[0]=='easy')})")


if __name__ == "__main__":
    main()
