"""Conjunto de avaliação do agrupamento (Fase 2.1).

100 pares título×título rotulados manualmente. Mede o predicado par-a-par
(pair_decision) para não depender da ordem do union-find.
Portões atuais = desempenho medido em 30/10 após 2.3 (P=0.96, R=0.63); subir ao melhorar.
"""
import json
import os

import app

FIXTURE = os.path.join(os.path.dirname(__file__), "eval_pairs.jsonl")


def load():
    with open(FIXTURE, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def scores(thresh=0.38):
    pairs = [(p["a_title"], p["b_title"], p["label"],
              p.get("a_source"), p.get("b_source")) for p in load()]
    return app.eval_pairs(pairs, thresh)


def test_eval_precision_recall():
    prec, rec, (tp, fp, fn, tn) = scores()
    print(f"\nP={prec:.3f} R={rec:.3f} (TP={tp} FP={fp} FN={fn} TN={tn})")
    assert prec >= 0.94, f"precisão regrediu: {prec:.3f}"
    assert rec >= 0.60, f"revocação regrediu: {rec:.3f}"
