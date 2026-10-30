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
