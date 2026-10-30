#!/usr/bin/env python3
"""Compara TF-IDF vs embeddings no conjunto de avaliação (Fase 2.2).

Não é teste de portão (modelo pesado): roda manual e reporta P/R por variante.
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import app  # noqa: E402


def load_pairs():
    with open(os.path.join(BASE, "tests", "eval_pairs.jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def main():
    rows = load_pairs()
    pairs = [(r["a_title"], r["b_title"], r["label"]) for r in rows]
    titles = [t for p in pairs for t in (p[0], p[1])]

    print("calculando TF-IDF...", flush=True)
    Xt = app.tfidf_matrix([{"title": t} for t in titles])
    print("calculando embeddings...", flush=True)
    Xe = app.embed_matrix([{"title": t} for t in titles])

    def decide(k, mode):
        a, b, _ = pairs[k]
        ct = float(Xt[2 * k] @ Xt[2 * k + 1])
        ce = float(Xe[2 * k] @ Xe[2 * k + 1])
        sh = len(set(app.tok(a)) & set(app.tok(b)))
        t_rule = ct >= 0.38 and sh >= 2
        if mode == "tfidf":
            return t_rule
        if mode.startswith("emb"):
            t = float(mode[3:]) / 100
            return ce >= t and sh >= 2
        if mode.startswith("hyb"):
            t = float(mode[3:]) / 100
            return t_rule or (ce >= t and sh >= 1)
        raise ValueError(mode)

    for mode in ["tfidf", "emb60", "emb65", "emb70", "hyb60", "hyb65", "hyb70"]:
        tp = fp = fn = tn = 0
        misses = []
        for k, (_, _, label) in enumerate(pairs):
            pred = decide(k, mode)
            if pred and label == 1:
                tp += 1
            elif pred:
                fp += 1
                misses.append(("FP", rows[k]["id"]))
            elif label == 1:
                fn += 1
                misses.append(("FN", rows[k]["id"]))
            else:
                tn += 1
        p = tp / max(1, tp + fp)
        r = tp / max(1, tp + fn)
        print(f"{mode:7} P={p:.3f} R={r:.3f} (TP={tp} FP={fp} FN={fn} TN={tn})")
    print("\n(hyb = tfidf OU (emb>=T e 1+ token em comum))")


if __name__ == "__main__":
    main()
