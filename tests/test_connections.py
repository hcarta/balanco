"""Portões de precisão das conexões (F1.3).

O conjunto `tests/conn_pairs.jsonl` foi rotulado à mão em 31/10/2026 sobre
amostra estratificada do pré-filtro (ver `ops/sample_conn_pairs.py` e o
critério em PLANO_CONEXOES.md §F1.2). Cada teste aqui impede que uma mudança
futura degrade a conexão sem que alguém veja.

Medido na criação (31/10/2026):
  longform: P 0.94 / R 0.62   (60 pares, 26 positivos)
  intl:     P 1.00 / R 0.91   (40 pares, 11 positivos; F3.4)
  check:    P 1.00 / R 0.67   (67 pares,  3 positivos — amostra pequena por
                                desenho: checagem de mesma alegação é rara;
                                F4.2 recupera 2/3 sem FP)
"""
import json
import os

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAIRS = os.path.join(BASE, "tests", "conn_pairs.jsonl")
FIXTURE = os.path.join(BASE, "tests", "fixtures", "corpus_2026-10-31.json")


def load(kind):
    with open(PAIRS, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    return [p for p in rows if p["kind"] == kind]


def _fixture_titles():
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    bg = [s["title"] for s in data["stories"]]
    bg += [a["title"] for s in data["stories"] for a in s["articles"]]
    bg += [c["title"] for c in data.get("factchecks", [])]
    return bg


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
    from app import _world_match, entities
    sub = load("intl")
    preds = [_world_match(entities(p["a_title"]), p["b_title"],
                          p.get("b_summary", ""))[0] for p in sub]
    prec, rec, cm = _pr(preds, [p["label"] for p in sub])
    assert prec >= 0.90, f"precisão do Lá fora caiu: {prec:.2f} {cm}"
    assert rec >= 0.85, f"revogação do Lá fora caiu: {rec:.2f} {cm}"


def test_world_translates_anchors():
    """F3.4: Ucrânia/Ukraine é a mesma âncora (IN069)."""
    from app import _world_match, entities
    a = "EUA aprovam venda de 500 mísseis Patriot para a Ucrânia"
    b = "US approves sale of 500 Patriot missiles to Ukraine"
    ok, terms = _world_match(entities(a), b)
    assert ok, terms
    assert "ukraine" in terms


def test_world_summary_needs_strong_entity():
    """Resumo com entidade ampla não basta; multi-palavra específica basta."""
    from app import _world_match, entities
    story = entities("Lula anuncia pacote econômico")
    ok, _ = _world_match(story, "Trump signs executive order",
                         "Trump falou sobre a economia.")
    assert not ok

    story = entities("Flávio Bolsonaro foge para os EUA")
    ok, terms = _world_match(story,
                             "Trump and His Aides Helped Bolsonaro Flee Brazil",
                             "Flávio Bolsonaro embarcou para os Estados Unidos.")
    assert ok and "flávio bolsonaro" in terms


def test_fixture_is_frozen():
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    assert data["meta"]["frozen_at"] == "2026-10-31"
    assert len(data["stories"]) >= 100
    assert data["meta"]["n_articles"] >= 300
    assert len(data["factchecks"]) >= 60


def test_check_precision_gate():
    from app import build_idf, claim_match, tok
    sub = load("check")
    # Corpus congelado (F-12): ler docs/data.json fazia o portão derivar a
    # cada rodada do CI. A raridade tem de ser medida no mesmo corpus sempre.
    titles = [t for p in sub for t in (p["a_title"], p["b_title"])] + _fixture_titles()
    idf, df = build_idf([set(tok(t)) for t in titles])
    preds = [claim_match(set(tok(p["a_title"])), set(tok(p["b_title"])), idf, df,
                         0.34, p["a_title"], p["b_title"]) > 0
             for p in sub]
    prec, rec, cm = _pr(preds, [p["label"] for p in sub])
    assert prec >= 0.90, f"precisão das checagens caiu: {prec:.2f} {cm}"
    assert rec >= 0.60, f"revogação das checagens caiu: {rec:.2f} {cm}"


def test_claim_rejects_generic_overlap():
    """FPs reais de 31/10: "linha do tempo" e "Lula" isolado não são alegação."""
    from app import build_idf, claim_match, tok
    pairs = [
        ("Flávio: veja linha do tempo da fuga à carta golpista",
         "A crise do STF em 30 atos; veja linha do tempo"),
        ("Luana Piovani x Neymar: veja a linha do tempo da briga entre atriz e jogador",
         "A crise do STF em 30 atos; veja linha do tempo"),
        ("'Bolsonarismo não está derrotado, está disseminado. Basta ver os patrões de",
         "É falso que mais de 90% dos presos votaram em Lula"),
    ]
    bg = _fixture_titles()
    for a, b in pairs:
        idf, df = build_idf([set(tok(t)) for t in [a, b] + bg])
        assert claim_match(set(tok(a)), set(tok(b)), idf, df, 0.34, a, b) == 0


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
