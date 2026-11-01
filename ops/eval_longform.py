#!/usr/bin/env python3
"""Avalia o scorer do Aprofunde-se no conjunto C-3 (3 níveis).

Métricas: P@3 (top3 com label>=1), nDCG@3 (ganho 2/1/0) e P/R par-a-par
para "mesmo fato" (label 2) e "relevante" (label>=1).

Uso: python ops/eval_longform.py [--embed]
"""
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import app  # noqa: E402

PAIRS = os.path.join(BASE, "tests", "longform_pairs.jsonl")


def load():
    with open(PAIRS, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def features(pairs, use_embed=False):
    titles = [p["story_title"] for p in pairs] + [p["piece_title"] for p in pairs]
    idf, df = app.build_idf([set(app.tok(t)) for t in titles])
    emb = None
    if use_embed:
        try:
            X = app.embed_matrix([{"title": t} for t in titles])
            emb = X
        except Exception as e:
            print("[aviso] embeddings indisponíveis:", e)
    n = len(pairs)
    out = []
    for i, p in enumerate(pairs):
        se = app.entities(p["story_title"])
        pe = app.entities(p["piece_title"] + " " + (p.get("piece_summary") or ""))
        shared = se & pe
        spec = app._distinct_entities(shared)
        cov = app._title_cov(set(app.tok(p["story_title"])),
                             set(app.tok(p["piece_title"])))
        den = sum(idf.get(e, 1) for e in pe) or 1
        ent = sum(idf.get(e, 1) for e in spec) / den
        age = float(p.get("age_days") or 0)
        rec = math.exp(-age / 60.0)
        quality = 1.0  # fontes longform; factualidade não muda o ranking
        em = float(X[i] @ X[n + i]) if emb is not None else 0.0
        out.append({
            "cov": cov, "ent": ent, "spec": len(spec), "age": age,
            "rec": rec, "quality": quality, "emb": em,
            "ok_entity": bool(spec),
            "label": p["label"], "story": p["story_title"],
            "id": p["id"],
        })
    return out


def rule(f):
    """Regra atual (conservadora), só para comparar."""
    if not f["ok_entity"]:
        return False
    if f["age"] <= 14:
        return True
    return f["spec"] >= 2 and f["cov"] >= 0.30


def score(f, mode):
    if mode == "rule":
        return (1.0 if rule(f) else 0.0) + 0.01 * f["cov"] + 0.001 * f["ent"]
    if mode == "lex":
        return 0.60 * f["cov"] + 0.40 * f["ent"]
    if mode == "lex_rec":
        return 0.55 * f["cov"] + 0.30 * f["ent"] + 0.10 * f["rec"] + 0.05 * f["quality"]
    if mode == "emb":
        return (0.45 * f["emb"] + 0.30 * f["ent"] + 0.10 * f["rec"]
                + 0.10 * f["quality"] + 0.05 * f["cov"])
    raise ValueError(mode)


def ndcg_at(ranked, k=3, gains=(0, 1, 2)):
    dcg = 0.0
    for j, f in enumerate(ranked[:k]):
        dcg += gains[f["label"]] / math.log2(j + 2)
    ideal = sorted((gains[f["label"]] for f in ranked), reverse=True)[:k]
    idcg = sum(g / math.log2(j + 2) for j, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def p_at(ranked, k=3):
    top = ranked[:k]
    return sum(1 for f in top if f["label"] >= 1) / len(top) if top else 0.0


def group_metrics(fs, mode):
    stores = {}
    for f in fs:
        stores.setdefault(f["story"], []).append(f)
    nd, pt, groups = [], [], 0
    for items in stores.values():
        if len(items) < 2:
            continue
        ranked = sorted(items, key=lambda f: score(f, mode), reverse=True)
        nd.append(ndcg_at(ranked))
        pt.append(p_at(ranked))
        groups += 1
    return (sum(nd) / len(nd) if nd else 0.0,
            sum(pt) / len(pt) if pt else 0.0, groups)


def pr_at(fs, mode, positive, thr):
    tp = fp = fn = 0
    for f in fs:
        pred = score(f, mode) >= thr
        if positive(f) and pred:
            tp += 1
        elif pred:
            fp += 1
        elif positive(f):
            fn += 1
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (tp, fp, fn)


def main():
    use_embed = "--embed" in sys.argv
    pairs = load()
    fs = features(pairs, use_embed)
    print(f"{len(pairs)} pares; labels:",
          {k: sum(1 for f in fs if f["label"] == k) for k in (0, 1, 2)})
    nd, pt, ng = group_metrics(fs, "rule")
    print(f"regra atual: P@3={pt:.2f} nDCG@3={nd:.3f} ({ng} histórias)")
    for mode in (["lex", "lex_rec"] + (["emb"] if use_embed else [])):
        nd, pt, ng = group_metrics(fs, mode)
        print(f"{mode:8} P@3={pt:.2f} nDCG@3={nd:.3f} ({ng} histórias)")
        for positive, name in ((lambda f: f["label"] == 2, "same"),
                               (lambda f: f["label"] >= 1, "rel")):
            best = None
            for thr in [x / 100 for x in range(5, 96, 5)]:
                p, r, cm = pr_at(fs, mode, positive, thr)
                if p >= 0.80 and (best is None or r > best[2]):
                    best = (thr, p, r, cm)
            if best:
                print(f"  {name:4} thr={best[0]:.2f} P={best[1]:.2f} "
                      f"R={best[2]:.2f} {best[3]}")


if __name__ == "__main__":
    main()
