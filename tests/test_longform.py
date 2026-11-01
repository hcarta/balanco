"""Portões do conjunto C-3 (Aprofunde-se em 3 níveis).

Rotulagem única (agente), 01/11/2026: 120 pares, 55 da piauí, níveis
2 (mesmo fato), 1 (pano de fundo) e 0 (irrelevante). O teste mede a regra
conservadora de produção; o scorer híbrido com embeddings é opt-in
(`ops/eval_longform.py --embed`) e ainda não roda no CI.
"""
import importlib.util
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAIRS = os.path.join(BASE, "tests", "longform_pairs.jsonl")
EVAL = os.path.join(BASE, "ops", "eval_longform.py")


def load():
    with open(PAIRS, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def eval_module():
    spec = importlib.util.spec_from_file_location("eval_longform", EVAL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_longform_dataset_has_support():
    pairs = load()
    assert len(pairs) >= 120
    assert sum(p["piece_source"] == "Revista piauí" for p in pairs) >= 40
    from collections import Counter
    labels = Counter(p["label"] for p in pairs)
    assert labels[2] >= 12, f"poucos 'mesmo fato': {labels}"
    assert labels[1] >= 20, f"poucos 'pano de fundo': {labels}"
    assert labels[0] >= 40


def test_longform_rule_ndcg_gate():
    mod = eval_module()
    fs = mod.features(load())
    nd, pt, groups = mod.group_metrics(fs, "rule")
    assert groups >= 15
    assert pt >= 0.50, f"P@3 caiu: {pt:.2f}"
    assert nd >= 0.65, f"nDCG@3 caiu: {nd:.3f}"
