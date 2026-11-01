"""F2: treina e calibra o gate de par (same vs resto).

Split por componentes de títulos compartilhados (os 154 pares vêm de uma
única janela de 72 h, então split por data é inviável; componentes evitam
que o mesmo título vaze entre train/test).

Uso:
    python ops/eval_pair_model.py --pairs tests/cluster_pairs.jsonl --seed 7
    python ops/eval_pair_model.py --pairs tests/cluster_pairs.jsonl --save state/pair_model.json

Artefato (sem pickle; inferência só-numpy em app.py):
    {"features": [...], "mean": [...], "scale": [...],
     "coef": [...], "intercept": float, "threshold": float, "metrics": {...}}
"""
import argparse
import json
import unicodedata

import numpy as np

LABEL = "same"


def norm(x):
    return unicodedata.normalize("NFKD", (x or "")).encode("ascii", "ignore") \
        .decode().lower().strip()


def load(pairs_path):
    recs = []
    with open(pairs_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                recs.append(json.loads(line))
    return recs


def components(recs):
    parent = list(range(len(recs)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    by_title = {}
    for i, r in enumerate(recs):
        for t in (norm(r["a"]), norm(r["b"])):
            by_title.setdefault(t, []).append(i)
    for idxs in by_title.values():
        for j in idxs[1:]:
            union(idxs[0], j)
    groups = {}
    for i in range(len(recs)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def split(recs, seed=7):
    """Componentes inteiros para train/test, estratificado por label."""
    from collections import defaultdict
    rng = np.random.RandomState(seed)
    comps = components(recs)
    by_lab = defaultdict(list)
    for c in comps:
        labs = [recs[i]["label"] for i in c]
        key = LABEL if LABEL in labs else ("related" if "related" in labs
                                           else labs[0])
        by_lab[key].append(c)
    train, test = [], []
    for key, cs in by_lab.items():
        rng.shuffle(cs)
        cut = max(1, int(len(cs) * 0.65)) if len(cs) > 1 else 0
        train += [i for c in cs[:cut] for i in c]
        test += [i for c in cs[cut:] for i in c]
    if not test:  # dobra mínima: move o menor componente para test
        c = min(comps, key=len)
        train = [i for i in train if i not in c]
        test = list(c)
    return sorted(train), sorted(test)


def load_features(path="state/pair_features.jsonl"):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="tests/cluster_pairs.jsonl")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--save", default=None)
    args = ap.parse_args()

    recs = load(args.pairs)
    feat_rows = load_features()
    assert len(feat_rows) == len(recs), "features fora de sincronia com pares"
    names = list(feat_rows[0]["features"].keys())
    # cos_emb = -1 quando as features foram geradas sem --embed
    if all(row["features"].get("cos_emb", -1.0) == -1.0 for row in feat_rows):
        names = [n for n in names if n != "cos_emb"]
        print("(sem cos_emb: features geradas sem --embed)")
    X = np.array([[row["features"][k] for k in names] for row in feat_rows],
                 dtype=float)
    y = np.array([1 if r["label"] == LABEL else 0 for r in recs])

    train, test = split(recs, seed=args.seed)
    print(f"pares: {len(recs)} (same {y.sum()}, resto {len(y)-y.sum()})")
    print(f"train: {len(train)} (same {y[train].sum()}) | "
          f"test: {len(test)} (same {y[test].sum()})")

    from sklearn.linear_model import LogisticRegression
    mu = X[train].mean(axis=0)
    sd = X[train].std(axis=0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000)
    clf.fit(Z[train], y[train])
    prob = clf.predict_proba(Z)[:, 1]

    def pr(ids, thr):
        p = prob[ids]
        pred = p >= thr
        tp = int(((pred == 1) & (y[ids] == 1)).sum())
        fp = int(((pred == 1) & (y[ids] == 0)).sum())
        fn = int(((pred == 0) & (y[ids] == 1)).sum())
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        return prec, rec, (tp, fp, fn)

    best = None
    for thr in [x / 100 for x in range(5, 96)]:
        p, r, _ = pr(train, thr)
        if p >= 0.97 and (best is None or r > best[1]):
            best = (thr, r, p)
    if best is None:  # sem limiar P>=0.97 no train: pega a maior precisão
        cands = [(pr(train, t / 100)[0], t / 100) for t in range(5, 96)]
        cands.sort(reverse=True)
        thr = cands[0][1]
        print(f"AVISO: nenhum limiar com P>=0.97 no train; usando P máxima "
              f"thr={thr:.2f}")
    else:
        thr, _, _ = best
    ptr, rtr, cmtr = pr(train, thr)
    pte, rte, cmte = pr(test, thr)
    print(f"thr={thr:.2f} train: P={ptr:.2f} R={rtr:.2f} {cmtr}")
    print(f"thr={thr:.2f} test:  P={pte:.2f} R={rte:.2f} {cmte}")

    # different com prob alta = alarme (aceite F2)
    bad = [(float(prob[i]), r["label"], r["a"][:60], r["b"][:60])
           for i, r in enumerate(recs)
           if r["label"] == "different" and prob[i] >= 0.5]
    print(f"different com p>=0.5: {len(bad)}")
    for p, lab, a, b in sorted(bad, reverse=True)[:10]:
        print(f"  p={p:.2f} {a} × {b}")

    # 20 erros mais confiantes (revisão)
    errs = []
    for i, r in enumerate(recs):
        pred = prob[i] >= thr
        if bool(pred) != bool(y[i]):
            errs.append((abs(prob[i] - thr), r["label"], r["a"][:55],
                         r["b"][:55], float(prob[i])))
    print(f"erros no thr (train+test): {len(errs)}; top confiantes:")
    for c, lab, a, b, p in sorted(errs, reverse=True)[:20]:
        print(f"  p={p:.2f} [{lab}] {a} × {b}")

    print("coeficientes (top |.|):")
    for k, c in sorted(zip(names, clf.coef_[0]), key=lambda kv: -abs(kv[1]))[:10]:
        print(f"  {k:15} {c:+.3f}")

    if args.save:
        model = {"features": names, "mean": mu.tolist(),
                 "scale": sd.tolist(), "coef": clf.coef_[0].tolist(),
                 "intercept": float(clf.intercept_[0]),
                 "threshold": thr,
                 # F3: veto de elo fraco (medido: 6% dos same e 56% dos
                 # related ficam abaixo em 0,25)
                 "veto_threshold": 0.25,
                 "metrics": {"train": {"P": ptr, "R": rtr, "cm": cmtr},
                             "test": {"P": pte, "R": rte, "cm": cmte}}}
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(model, f, ensure_ascii=False, indent=1)
        print("modelo →", args.save)


if __name__ == "__main__":
    main()
