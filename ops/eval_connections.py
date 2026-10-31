#!/usr/bin/env python3
"""Avaliação das conexões sobre o conjunto rotulado (F1.3).

Mede, por conexão, precisão e revogação de cada sinal isolado e da combinação,
em vários limiares. Sem isso, "melhorar o matcher" é escolher número no escuro.

Uso: python ops/eval_connections.py [--no-embed]
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import app  # noqa: E402

PAIRS = os.path.join(BASE, "tests", "conn_pairs.jsonl")


def load():
    with open(PAIRS, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def pr(scores, labels, thr):
    tp = fp = fn = 0
    for s, y in zip(scores, labels):
        pred = s >= thr
        if pred and y:
            tp += 1
        elif pred:
            fp += 1
        elif y:
            fn += 1
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (tp, fp, fn)


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    ph = k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    m = z * ((ph * (1 - ph) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - m), min(1.0, c + m))


def signals(pairs, use_embed=True):
    """Score de cada par por sinal: entidade, cobertura, embedding, híbrido."""
    titles = [p["a_title"] for p in pairs] + [p["b_title"] for p in pairs]
    n = len(pairs)
    _, df = app.build_idf([set(app.tok(t)) for t in titles])
    out = {"ent": [], "cov": [], "emb": []}
    X = None
    if use_embed:
        try:
            X = app.embed_matrix([{"title": t} for t in titles])
        except Exception as e:
            print(f"[aviso] embeddings indisponíveis: {e}")
    for i, p in enumerate(pairs):
        ea, eb = app.entities(p["a_title"]), app.entities(p["b_title"])
        ok, _ = app.entity_match(ea, eb)
        ta, tb = set(app.tok(p["a_title"])), set(app.tok(p["b_title"]))
        cov = app._title_cov(ta, tb)
        rare = sum(1 for w in ta & tb if df.get(w, 99) <= 12)
        out["ent"].append(1.0 if ok else 0.0)
        out["cov"].append(cov if rare >= 2 else 0.0)
        out["emb"].append(float(X[i] @ X[n + i]) if X is not None else 0.0)
    return out


def report(name, pairs, sig):
    labels = [p["label"] for p in pairs]
    pos = sum(labels)
    print(f"\n=== {name}: {len(pairs)} pares, {pos} positivos ({pos/len(pairs):.0%}) ===")
    for key, label in (("ent", "entidade (regra atual)"),
                       ("cov", "cobertura+tokens raros"),
                       ("emb", "embedding")):
        s = sig[key]
        if max(s) == 0 and min(s) == 0:
            print(f"  {label:28} indisponível")
            continue
        best = None
        for thr in ([0.5] if key == "ent" else
                    [x / 100 for x in range(10, 91, 5)]):
            p, r, cm = pr(s, labels, thr)
            if p >= 0.90 and (best is None or r > best[2]):
                best = (thr, p, r, cm)
        if best:
            lo, hi = wilson(best[3][0], best[3][0] + best[3][1])
            print(f"  {label:28} melhor P≥0.90 em thr={best[0]:.2f}: "
                  f"P={best[1]:.2f} (IC95 {lo:.2f}–{hi:.2f}) R={best[2]:.2f} {best[3]}")
        else:
            p, r, cm = pr(s, labels, 0.5 if key == "ent" else 0.5)
            print(f"  {label:28} sem ponto com P≥0.90 (em 0.50: P={p:.2f} R={r:.2f})")


def main():
    use_embed = "--no-embed" not in sys.argv
    pairs = load()
    for kind in ("longform", "intl", "check"):
        sub = [p for p in pairs if p["kind"] == kind]
        if not sub:
            continue
        if kind == "check":
            # Checagem usa claim_match. O IDF inclui o corpus real (histórias,
            # matérias e checagens do data.json), não só os 134 títulos dos
            # pares: medir raridade no conjunto pequeno inflava o recall.
            with open(os.path.join(BASE, "docs", "data.json"), encoding="utf-8") as f:
                data = json.load(f)
            bg = [s["title"] for s in data["stories"]]
            bg += [a["title"] for s in data["stories"] for a in s["articles"]]
            bg += [c["title"] for c in data.get("factchecks", [])]
            titles = [t for p in sub for t in (p["a_title"], p["b_title"])] + bg
            idf, df = app.build_idf([set(app.tok(t)) for t in titles])
            scores = [app.claim_overlap(set(app.tok(p["a_title"])),
                                        set(app.tok(p["b_title"])), idf, df)
                      for p in sub]
            labels = [p["label"] for p in sub]
            print(f"\n=== check: {len(sub)} pares, {sum(labels)} positivos ===")
            for thr in (0.0, 0.34, 0.45, 0.60):
                p, r, cm = pr(scores, labels, thr)
                print(f"  claim_overlap thr={thr:.2f}: P={p:.2f} R={r:.2f} {cm}")
            prod = [app.claim_match(set(app.tok(p["a_title"])),
                                    set(app.tok(p["b_title"])), idf, df) > 0
                    for p in sub]
            p, r, cm = pr([1.0 if x else 0.0 for x in prod], labels, 0.5)
            print(f"  produção (claim_match)          P={p:.2f} R={r:.2f} {cm}")
            continue
        report(kind, sub, signals(sub, use_embed))
        if kind == "intl":
            from app import _world_match, entities as _ents
            preds = [_world_match(_ents(p["a_title"]), p["b_title"],
                                  p.get("b_summary", ""))[0] for p in sub]
            labels = [p["label"] for p in sub]
            prec, rec, cm = pr([1.0 if x else 0.0 for x in preds], labels, 0.5)
            print(f"  {'produção (título+resumo+âncoras)':28} "
                  f"P={prec:.2f} R={rec:.2f} {cm}")


if __name__ == "__main__":
    main()
