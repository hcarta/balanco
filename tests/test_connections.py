"""Portões de precisão das conexões (F1.3).

O conjunto `tests/conn_pairs.jsonl` foi rotulado à mão em 31/10/2026 sobre
amostra estratificada do pré-filtro (ver `ops/sample_conn_pairs.py` e o
critério em PLANO_CONEXOES.md §F1.2). Cada teste aqui impede que uma mudança
futura degrade a conexão sem que alguém veja.

Medido na criação (31/10/2026):
  longform: P 0.94 / R 0.62   (60 pares, 26 positivos)
  intl:     P 1.00 / R 0.73   (40 pares, 11 positivos)
  check:    P 1.00 / R 0.33   (67 pares,  3 positivos — amostra pequena por
                                desenho: checagem de mesma alegação é rara)
"""
import json
import os

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAIRS = os.path.join(BASE, "tests", "conn_pairs.jsonl")


def load(kind):
    with open(PAIRS, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    return [p for p in rows if p["kind"] == kind]


def _pr(preds, labels):
    tp = sum(1 for p, y in zip(preds, labels) if p and y)
    fp = sum(1 for p, y in zip(preds, labels) if p and not y)
    fn = sum(1 for p, y in zip(preds, labels) if not p and y)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return prec, rec, (tp, fp, fn)


def test_conn_set_has_support():
    """Se o arquivo for truncado, os portões abaixo passariam vazios."""
    assert len(load("longform")) >= 55
    assert sum(p["label"] for p in load("longform")) >= 20
    assert len(load("intl")) >= 35
    assert sum(p["label"] for p in load("intl")) >= 8
    assert len(load("check")) >= 60


def test_longform_precision_gate():
    from app import entities, entity_match
    sub = load("longform")
    preds = [entity_match(entities(p["a_title"]), entities(p["b_title"]))[0] for p in sub]
    prec, rec, cm = _pr(preds, [p["label"] for p in sub])
    assert prec >= 0.90, f"precisão do Aprofunde-se caiu: {prec:.2f} {cm}"
    assert rec >= 0.55, f"revogação do Aprofunde-se caiu: {rec:.2f} {cm}"


def test_intl_precision_gate():
    from app import entities, entity_match
    sub = load("intl")
    preds = [entity_match(entities(p["a_title"]), entities(p["b_title"]))[0] for p in sub]
    prec, rec, cm = _pr(preds, [p["label"] for p in sub])
    assert prec >= 0.90, f"precisão do Lá fora caiu: {prec:.2f} {cm}"
    assert rec >= 0.65, f"revogação do Lá fora caiu: {rec:.2f} {cm}"


def test_check_precision_gate():
    from app import build_idf, claim_overlap, tok
    sub = load("check")
    titles = [t for p in sub for t in (p["a_title"], p["b_title"])]
    idf, df = build_idf([set(tok(t)) for t in titles])
    preds = [claim_overlap(set(tok(p["a_title"])), set(tok(p["b_title"])), idf, df) > 0
             for p in sub]
    prec, rec, cm = _pr(preds, [p["label"] for p in sub])
    assert prec >= 0.90, f"precisão das checagens caiu: {prec:.2f} {cm}"


def test_embed_boost_does_not_hurt_precision():
    """Ganho opt-in (--embed): entidade OR embedding >= 0.75."""
    pytest.importorskip("sentence_transformers")
    from app import EMB_BOOST, embed_matrix, entities, entity_match
    sub = load("longform") + load("intl")
    titles = [p["a_title"] for p in sub] + [p["b_title"] for p in sub]
    n = len(sub)
    try:
        X = embed_matrix([{"title": t} for t in titles])
    except Exception as e:  # modelo não baixado neste ambiente
        pytest.skip(f"modelo de embedding indisponível: {e}")
    lex, hyb = [], []
    for i, p in enumerate(sub):
        ok, _ = entity_match(entities(p["a_title"]), entities(p["b_title"]))
        lex.append(ok)
        hyb.append(ok or float(X[i] @ X[n + i]) >= EMB_BOOST)
    labels = [p["label"] for p in sub]
    p_lex, r_lex, _ = _pr(lex, labels)
    p_hyb, r_hyb, _ = _pr(hyb, labels)
    assert p_hyb >= 0.90, f"híbrido perdeu precisão: {p_hyb:.2f}"
    assert p_hyb >= p_lex - 0.02, f"híbrido degradou precisão: {p_lex:.2f}→{p_hyb:.2f}"
    assert r_hyb >= r_lex, f"híbrido não trouxe revogação: {r_lex:.2f}→{r_hyb:.2f}"


def test_embed_boost_requires_lexical_anchor(monkeypatch):
    """Sem âncora lexical, embedding alto NÃO pode criar conexão.

    Regressão do bug de 31/10/2026: aplicar o boost a todos os pares ligava
    "diplomata argentina" a "voto das capitais" (cosseno alto, zero relação).
    """
    import numpy as np
    import app

    # embedding artificialmente perfeito: todo par tem cosseno 1.0
    monkeypatch.setattr(app, "embed_matrix",
                        lambda items: np.ones((len(items), 4), dtype="float32"))
    story = {"title": "Brasil convoca diplomata argentina sobre fuga de Flávio Bolsonaro",
             "articles": []}
    art = {"title": "A diferença no voto das capitais e do interior no 2º turno",
           "link": "https://exemplo/1", "source_id": "nexo",
           "source_name": "Nexo Jornal"}
    app.attach_longreads([story], [art], {"nexo"}, use_embed=True)
    assert story["longreads"] == []

    story2 = {"title": "Brasil convoca diplomata argentina sobre fuga de Flávio Bolsonaro",
              "articles": []}
    world = {"title": "How crypto hacking funds North Korea's nuclear programme",
             "link": "https://exemplo/2", "source_id": "guardian",
             "source_name": "The Guardian"}
    app.attach_world([story2], [world], use_embed=True)
    assert story2["world"] == []


def test_longform_matches_title_not_summary():
    """Resumo mencionando o tema não pode criar conexão (bug de 31/10/2026)."""
    import app
    story = {"title": "Brasil convoca diplomata argentina sobre fuga de Flávio Bolsonaro",
             "articles": []}
    art = {"title": "A diferença no voto das capitais e do interior no 2º turno",
           "summary": "Análise cita Flávio Bolsonaro e a fuga para os EUA.",
           "link": "https://exemplo/3", "source_id": "nexo",
           "source_name": "Nexo Jornal"}
    app.attach_longreads([story], [art], {"nexo"})
    assert story["longreads"] == []


def test_world_piece_not_repeated_across_stories():
    """A mesma peça internacional fica em uma só história (F1.4)."""
    import app
    stories = [{"title": "Flávio Bolsonaro foge para os EUA", "articles": []},
               {"title": "Flávio Bolsonaro fala pela primeira vez dos EUA", "articles": []}]
    art = {"title": "Flávio Bolsonaro flees to the US", "link": "https://exemplo/4",
           "source_id": "guardian", "source_name": "The Guardian"}
    app.attach_world(stories, [art])
    assert sum(len(s["world"]) for s in stories) == 1
