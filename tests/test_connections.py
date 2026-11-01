"""Portões de precisão das conexões (F1.3).

O conjunto `tests/conn_pairs.jsonl` foi rotulado à mão em 31/10/2026 sobre
amostra estratificada do pré-filtro (ver `ops/sample_conn_pairs.py` e o
critério em PLANO_CONEXOES.md §F1.2). Cada teste aqui impede que uma mudança
futura degrade a conexão sem que alguém veja.

Medido na criação (31/10/2026):
  longform: P 0.94 / R 0.62   (60 pares, 26 positivos)
  intl:     P 1.00 / R 0.91   (40 pares, 11 positivos; F3.4 + B-3)
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
                          p.get("b_summary", ""), p["a_title"])[0] for p in sub]
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


def test_world_matches_event_number():
    """Binance: entidade única + número do evento (US$ 6,3 bi) basta (31/10)."""
    from app import _world_match, entities
    a = ("Binance sofre ataque hacker de US$ 6,3 bilhões: por que Coreia do Norte "
         "pode estar por trás do possível maior roubo da história das criptomoedas")
    b = "Binance’s $6.3 Billion Hack Is Just the Start of a Risky New Era"
    ok, terms = _world_match(entities(a), b, "The largest cyber heist in history.", a)
    assert ok and "binance" in terms


def test_world_number_needs_shared_entity():
    from app import _world_match, entities
    a = "Lula anuncia pacote de R$ 10 bilhões"
    b = "Trump signs $10 billion package"
    ok, _ = _world_match(entities(a), b, "", a)
    assert not ok


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


def test_world_matches_concept_without_number():
    from app import _world_match, entities
    a = "Ataque hacker atinge a Binance"
    b = "Binance hack: what we know"
    ok, _ = _world_match(entities(a), b, "", a)
    assert ok


def test_world_concept_rejects_person_only():
    from app import _world_match, entities
    a = "Lula defende propostas para o quarto mandato"
    b = "Brazil’s victory: seven lessons from Lula’s win"
    ok, _ = _world_match(entities(a), b, "", a)
    assert not ok


def test_world_concept_needs_shared_entity():
    from app import _world_match, entities
    a = "Lula anuncia pacote econômico"
    b = "Trump wins election"
    ok, _ = _world_match(entities(a), b, "", a)
    assert not ok


def test_intl_groups_by_entity_and_number():
    import time
    import app
    now = time.time()
    arts = [
        {"source_id": "bbc", "source_name": "BBC",
         "title": "What we know about Binance's $6.3bn hack",
         "link": "b", "summary": "", "ts": now, "section": "mundo"},
        {"source_id": "nytimes", "source_name": "NYT",
         "title": "How Binance's $6.3 Billion Hack Went Down",
         "link": "n", "summary": "", "ts": now, "section": "mundo"},
        {"source_id": "other", "source_name": "Other",
         "title": "Ebola outbreak", "link": "e", "summary": "",
         "ts": now, "section": "mundo"},
    ]
    groups = app.group_intl_articles(arts)
    assert any({a["link"] for a in g} == {"b", "n"} for g in groups)
    story = {"id": "s1", "title": "Binance sofre ataque hacker de US$ 6,3 bilhões",
             "counts": {"total": 2}, "articles": []}
    out = app.attach_world([story], arts)
    w = out[0]["world"]
    assert len(w) == 1
    assert w[0]["n_sources"] == 2
    assert any(s["source"] == "BBC" for s in w[0]["sources"])


def _lr_story(title, link="https://x/s", ts=None):
    import time
    return {"id": "h1", "title": title, "summary": "",
            "articles": [{"source": "G1", "title": title, "link": link}],
            "counts": {"total": 1}, "updated": "2026-11-01T10:00:00+00:00"}


def _lr_piece(title, summary="", ts=None, source_id="piaui", link="https://x/p"):
    import time
    return {"title": title, "summary": summary, "link": link,
            "source_id": source_id, "source_name": "Piauí",
            "ts": ts or time.time(), "section": "reportagem"}


def test_longform_hybrid_admits_with_anchor_but_no_entity_match(monkeypatch):
    """C-3: com --embed, a âncora lexical + scorer >= limiar admite;
    sem embed, a regra de entidade barra. Sem modelo real (mock)."""
    import numpy as np
    import app
    story = "Banco Master: como Vorcaro transformou o banco em plataforma"
    piece = "O instituto de Mendonça e o caso Master no STF"
    st = _lr_story(story)
    pc = _lr_piece(piece, summary="Mendonça e o caso Master no Supremo")
    # âncora lexical existe, mas entity_match exige 2+ entidades
    assert app._title_cov(set(app.tok(story)), set(app.tok(piece))) >= app.EMB_PREFILTER_COV
    assert app.entity_match(app.entities(story), app.entities(piece))[0] is False

    def fake_embed(docs):
        n = len(docs)
        X = np.zeros((n, 2))
        X[0] = [1.0, 0.0]   # história
        X[1] = [1.0, 0.0]   # peça: cosseno 1.0
        return X

    monkeypatch.setattr(app, "embed_matrix", fake_embed)
    got = app.attach_longreads([dict(st)], [dict(pc)], {"piaui"}, use_embed=True)
    assert len(got[0]["longreads"]) == 1, "scorer alto + âncora deveria admitir"

    def fake_zero(docs):
        n = len(docs)
        X = np.zeros((n, 2))
        X[0] = [1.0, 0.0]
        X[1] = [0.0, 1.0]   # cosseno 0.0
        return X

    monkeypatch.setattr(app, "embed_matrix", fake_zero)
    got2 = app.attach_longreads([dict(st)], [dict(pc)], {"piaui"}, use_embed=True)
    assert got2[0]["longreads"] == [], "scorer baixo não admite"

    got3 = app.attach_longreads([dict(st)], [dict(pc)], {"piaui"},
                                use_embed=False)
    assert got3[0]["longreads"] == [], "sem embed a regra barra (fallback)"


def test_longform_hybrid_orders_by_emb_score(monkeypatch):
    import numpy as np
    import app
    story = "Crise no Banco Master chega ao STF com Mendonça relator"
    st = _lr_story(story)
    p1 = _lr_piece("O instituto de Mendonça", summary="Mendonça e o Master",
                   link="https://x/p1")
    p2 = _lr_piece("Mendonça e o caso Master no STF: entenda a crise do banco",
                   summary="relatoria de Mendonça no caso Master",
                   link="https://x/p2")

    def fake_embed(docs):
        # docs = [história, p1, p2]; p1 cos 0.9, p2 cos 0.99
        X = np.array([[1.0, 0.0], [0.9, 0.436], [0.99, 0.141]])
        Xn = X / np.linalg.norm(X, axis=1, keepdims=True)
        return Xn

    monkeypatch.setattr(app, "embed_matrix", fake_embed)
    got = app.attach_longreads([dict(st)], [dict(p1), dict(p2)], {"piaui"},
                               use_embed=True)
    links = [lr["link"] for lr in got[0]["longreads"]]
    assert links and links[0] == "https://x/p2", f"maior emb_score primeiro: {links}"


def test_longform_pool_excludes_foro_de_teresina():
    """F-08: peça /web/ftNNN/ não entra no pool do Aprofunde-se."""
    import app
    assert app.piece_kind(
        {"title": "Vitória da democracia",
         "link": "https://piaui.uol.com.br/web/ft136/"}, None) == "podcast"
    story = _lr_story("Lula faz história e Flávio encena farsa")
    ft = _lr_piece("Vitória da democracia: Lula faz história e Flávio encena farsa golpista",
                   summary="Episódio com análise da semana",
                   link="https://piaui.uol.com.br/web/ft136/")
    got = app.attach_longreads([story], [ft], {"piaui"}, use_embed=False)
    assert got[0]["longreads"] == []
