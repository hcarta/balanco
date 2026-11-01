"""F2 (preparo): extração determinística de features de par.

Uso:
    python ops/pair_features.py --pairs tests/cluster_pairs.jsonl \
        --out state/pair_features.jsonl
    python ops/pair_features.py --pairs tests/cluster_pairs.jsonl \
        --out state/pair_features.jsonl --embed

Sem --embed, cos_emb = -1 (sentinela; o treino F2 decide como tratar).
O cosseno TF-IDF é calculado sobre o corpus fixo = todos os títulos do
arquivo de pares (mesmo harness do portão `test_cluster_pairs.py`).

Vetor fixo (FEATURE_NAMES, nesta ordem) — sklearn só no treino F2;
`app.py` usará inferência só-numpy a partir do JSON do modelo.
"""
import argparse
import json
import re
import sys
import time

sys.path.insert(0, ".")
import app
from app import ENTITY_GENERIC, entities, tfidf_matrix, tok

FEATURE_NAMES = [
    "cos_tfidf", "cos_emb", "jaccard", "cov_short", "cov_long",
    "shared_all", "shared_spec", "shared_multi", "shared_numbers",
    "numbers_match", "same_section", "same_group", "dt_hours",
    "len_a", "len_b", "ent_first3_a", "ent_first3_b", "subject_match",
    "rule_fused",
]

NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
GENERIC_TOK = {w.lower() for w in ENTITY_GENERIC}


def _numbers(title):
    return set(NUM_RE.findall(title or ""))


def _first3_ents(title):
    toks = tok(title)[:3]
    ents = entities(title)
    parts = {p for e in ents for p in e.split()}
    return 1 if any(t in parts for t in toks) else 0


def extract(a, b, cos, cos_emb=None, dt_hours=0.0,
            section_a=None, section_b=None, group_a=None, group_b=None,
            rule=None):
    """Vetor de features de um par. `a`/`b`: dicts com ao menos `title`."""
    ta, tb = a.get("title", ""), b.get("title", "")
    sa, sb = set(tok(ta)), set(tok(tb))
    shared = sa & sb
    union = sa | sb
    ea, eb = entities(ta), entities(tb)
    inter_ent = ea & eb
    na, nb = _numbers(ta), _numbers(tb)
    feats = {
        "cos_tfidf": round(float(cos), 4),
        "cos_emb": round(float(cos_emb), 4) if cos_emb is not None else -1.0,
        "jaccard": round(len(shared) / len(union), 4) if union else 0.0,
        "cov_short": round(len(shared) / min(len(sa), len(sb)), 4)
        if sa and sb else 0.0,
        "cov_long": round(len(shared) / max(len(sa), len(sb)), 4)
        if sa or sb else 0.0,
        "shared_all": len(shared),
        "shared_spec": len({w for w in shared if w not in GENERIC_TOK}),
        "shared_multi": len([e for e in inter_ent if " " in e]),
        "shared_numbers": len(na & nb),
        "numbers_match": 1 if (na and nb and na & nb) else 0,
        "same_section": 1 if (section_a and section_a == section_b) else 0,
        "same_group": 1 if (group_a and group_a == group_b) else 0,
        "dt_hours": round(float(dt_hours), 2),
        "len_a": len(sa),
        "len_b": len(sb),
        "ent_first3_a": _first3_ents(ta),
        "ent_first3_b": _first3_ents(tb),
        "subject_match": 1 if (tok(ta)[:2] and tok(tb)[:2]
                               and set(tok(ta)[:2]) & set(tok(tb)[:2])) else 0,
        "rule_fused": 1 if rule in ("fused", "near_dup_ok") else 0,
    }
    return [feats[k] for k in FEATURE_NAMES]


def build(pairs_path, use_embed=False):
    recs = [json.loads(l) for l in open(pairs_path, encoding="utf-8")
            if l.strip()]
    docs = []
    for r in recs:
        docs += [{"title": r["a"]}, {"title": r["b"]}]
    S = tfidf_matrix(docs) @ tfidf_matrix(docs).T
    Xe = None
    if use_embed:
        Xe = app.embed_matrix(docs)
        Se = Xe @ Xe.T
    else:
        Se = None
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
        toksets = [set(tok(arts[0]["title"])), set(tok(arts[1]["title"]))]
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
                    "rule_now": rule, "decision_now": "fused" if ok else "rejected",
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
    print(f"{len(rows)} pares → {args.out} "
          f"({len(FEATURE_NAMES)} features)")


if __name__ == "__main__":
    main()
