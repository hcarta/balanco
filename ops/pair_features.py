"""F2 (preparo): extrai features de par usando a MESMA função do app.

A definição vive em `app.pair_features` para treino e inferência não divergirem.

Uso:
    python ops/pair_features.py --pairs tests/cluster_pairs.jsonl \
        --out state/pair_features.jsonl
    python ops/pair_features.py --pairs tests/cluster_pairs.jsonl \
        --out state/pair_features.jsonl --embed

Sem --embed, cos_emb = -1 (sentinela; o treino descarta a coluna).
"""
import argparse
import json
import sys
import time

sys.path.insert(0, ".")
import app

FEATURE_NAMES = app.PAIR_FEATURE_NAMES


def extract(a, b, cos, cos_emb=None, dt_hours=0.0,
            section_a=None, section_b=None, group_a=None, group_b=None,
            rule=None):
    feats = app.pair_features(a, b, cos, cos_emb, dt_hours=dt_hours,
                              section_a=section_a, section_b=section_b,
                              group_a=group_a, group_b=group_b, rule=rule)
    return [feats[k] for k in FEATURE_NAMES]


def build(pairs_path, use_embed=False):
    recs = [json.loads(l) for l in open(pairs_path, encoding="utf-8")
            if l.strip()]
    docs = []
    for r in recs:
        docs += [{"title": r["a"]}, {"title": r["b"]}]
    S = app.tfidf_matrix(docs) @ app.tfidf_matrix(docs).T
    Se = None
    if use_embed:
        Xe = app.embed_matrix(docs)
        Se = Xe @ Xe.T
    now = time.time()
    out = []
    for k, r in enumerate(recs):
        i, j = 2 * k, 2 * k + 1
        arts = [
            {"title": r["a"], "ts": now,
             "source_id": r.get("source_a") or "sa",
             "section": r.get("section_a")},
            {"title": r["b"], "ts": now,
             "source_id": r.get("source_b") or "sb",
             "section": r.get("section_b")},
        ]
        toksets = [set(app.tok(arts[0]["title"])),
                   set(app.tok(arts[1]["title"]))]
        ok, rule = app._pair_decision(arts, toksets, S, Se, 0, 1, 0.38, 48)
        try:
            dt = abs(float(r.get("dt_h") or 0.0))
        except (TypeError, ValueError):
            dt = 0.0
        vec = extract(arts[0], arts[1], S[i, j],
                      Se[i, j] if Se is not None else None,
                      dt_hours=dt,
                      section_a=r.get("section_a"),
                      section_b=r.get("section_b"),
                      group_a=r.get("source_a"), group_b=r.get("source_b"),
                      rule=rule)
        out.append({"id": r.get("id", f"n{k}"), "label": r.get("label"),
                    "rule_now": rule,
                    "decision_now": "fused" if ok else "rejected",
                    "features": dict(zip(FEATURE_NAMES, vec))})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="tests/cluster_pairs.jsonl")
    ap.add_argument("--out", default="state/pair_features.jsonl")
    ap.add_argument("--embed", action="store_true")
    args = ap.parse_args()
    rows = build(args.pairs, use_embed=args.embed)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} pares → {args.out} ({len(FEATURE_NAMES)} features)")


if __name__ == "__main__":
    main()
