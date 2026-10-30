"""Matching história x checagem, bucket de viés, alertas e clustering básico."""
import time

import app
from app import bucket, build_idf, claim_overlap, cluster, store_alerts, tok

CORPUS = [
    "Itamaraty convoca diplomata argentina para explicar fuga de Flávio",
    "Itamaraty convoca coletiva sobre tarifas comerciais com vizinhos",
    "Itamaraty divulga nota oficial sobre reunião bilateral na segunda",
    "Governo Lula bloqueou Gás do Povo e Bolsa Família após eleições",
    "É FAKE que governo Lula bloqueou Gás do Povo e Bolsa Família",
    "Senado aprova marco fiscal em votação apertada no plenário",
]


def sets():
    return [set(tok(t)) for t in CORPUS]


def test_claim_overlap_same_claim_matches():
    idf, df = build_idf(sets())
    assert claim_overlap(sets()[3], sets()[4], idf, df) > 0


def test_claim_overlap_same_topic_does_not_match():
    idf, df = build_idf(sets())
    assert claim_overlap(sets()[0], sets()[1], idf, df) == 0.0


def test_claim_overlap_single_shared_token_is_zero():
    idf, df = build_idf(sets())
    a = set(tok("Itamaraty divulga nota sobre reunião bilateral"))
    b = set(tok("Senado divulga calendário de votações do semestre"))
    assert claim_overlap(a, b, idf, df) == 0.0


def test_bucket_thresholds():
    assert bucket(-1.5) == "L"
    assert bucket(-0.5) == "L"
    assert bucket(-0.3) == "C"
    assert bucket(0.0) == "C"
    assert bucket(0.2) == "C"
    assert bucket(0.5) == "R"
    assert bucket(1.6) == "R"


def test_rep_score_prefers_neutral_informative():
    from app import rep_score
    meta = {"bbc": {"factuality": "very_high"}, "blog": {"factuality": "low"}}
    neutral = {"title": "Itamaraty convoca diplomata argentina para esclarecer fuga de senador",
               "source_id": "bbc"}
    clickbait = {"title": "VOCÊ NÃO VAI ACREDITAR no que o Itamaraty fez ontem à noite?!",
                 "source_id": "bbc"}
    weak_src = {"title": "Itamaraty convoca diplomata argentina para esclarecer fuga de senador "
                         "e evitar uma crise diplomática sem precedentes na história",
                "source_id": "blog"}
    assert rep_score(neutral, meta) > rep_score(clickbait, meta)
    assert rep_score(neutral, meta) > rep_score(weak_src, meta)


def test_store_alerts_flags_errors_and_empty():
    h = {
        "ok": {"err_streak": 0, "empty": False, "last_status": "ok", "last_run": "x"},
        "bad": {"err_streak": 2, "empty": False, "last_status": "error", "last_run": "2026-10-30T20:00"},
        "dry": {"err_streak": 0, "empty": True, "last_status": "ok", "last_run": "2026-10-30T20:00"},
    }
    msgs = store_alerts(h)
    assert any("bad" in m for m in msgs)
    assert any("dry" in m for m in msgs)
    assert store_alerts({}) == []


def test_cluster_groups_near_duplicates():
    now = time.time()
    arts = [
        {"title": "Governo anuncia corte de impostos para empresas", "ts": now},
        {"title": "Governo anuncia corte de impostos para indústrias", "ts": now},
        {"title": "Festival de cinema exibe filmes nacionais premiados", "ts": now},
    ]
    groups = cluster(arts)
    assert len(groups) == 2
    pair = [g for g in groups if len(g) == 2][0]
    assert set(pair) == {0, 1}


def test_pair_window_by_section():
    from app import pair_window
    assert pair_window("politica", "politica") == 24.0
    assert pair_window("politica", None) == 24.0
    assert pair_window("vozes", "politica") == 168.0
    assert pair_window("opinião", "opinião") == 168.0  # com acento
    assert pair_window(None, None) == 48.0
    assert pair_window("tecnologia", "ciencia") == 48.0


def test_cluster_respects_section_window():
    now = time.time()
    day = 86400
    arts = [
        {"title": "Senado aprova marco fiscal em votação apertada", "ts": now,
         "section": "politica"},
        {"title": "Senado aprova marco fiscal em votação apertada no plenário",
         "ts": now - 30 * 3600, "section": "politica"},
        {"title": "Crítica teatral: a nova montagem de Hamlet no municipal", "ts": now,
         "section": "vozes"},
        {"title": "Crítica teatral: nova montagem de Hamlet em cartaz no municipal",
         "ts": now - 5 * day, "section": "vozes"},
    ]
    groups = cluster(arts, window_h=48)
    sizes = sorted(len(g) for g in groups)
    # breaking (30h) separa; opinião (5d) junta
    assert sizes == [1, 1, 2]
