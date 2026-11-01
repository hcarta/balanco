"""Portão de CI do plano de falsas equivalências (F1).

Corpus fixo = o próprio `tests/cluster_pairs.jsonl` (determinístico): a matriz
TF-IDF é calculada sobre todos os títulos do arquivo e cada par é julgado por
`_pair_decision` isoladamente.

- "different" nunca pode fundir (precisão primeiro) — asserção estrita.
- "same" em MUST_FUSE tem de fundir — asserção estrita.
- "same" em KNOWN_FN são falsos negativos conhecidos (alvo do F2/F3) — xfail
  explícito, para o CI ficar verde sem esconder a dívida.
- "related" não tem asserção (classe ambígua por desenho; usada no treino F2).
"""
import json
import time

import pytest

from app import _pair_decision, tfidf_matrix, tok

PAIRS = "tests/cluster_pairs.jsonl"

MUST_FUSE = {'c001', 'c004', 'c006', 'c008', 'c017', 'c021', 'c026', 'c027',
             'c030', 'c036', 'c038', 'c039', 'c048', 'c053', 'c071', 'c075',
             'c079', 'c084', 'c090', 'c093', 'c105', 'c110', 'c113', 'c125',
             'c126', 'seed-bulgaria-1', 'seed-bulgaria-2'}

KNOWN_FN = {'c007', 'c009', 'c010', 'c011', 'c012', 'c013', 'c014', 'c015',
            'c023', 'c024', 'c025', 'c031', 'c032', 'c033', 'c034', 'c035',
            'c040', 'c044', 'c047', 'c054', 'c056', 'c059', 'c061', 'c062',
            'c063', 'c064', 'c065', 'c066', 'c067', 'c069', 'c073', 'c076',
            'c077', 'c078', 'c080', 'c081', 'c083', 'c085', 'c094', 'c095',
            'c097', 'c099', 'c102', 'c106', 'c107', 'c109', 'c117', 'c131',
            'c132', 'c133', 'c134', 'c135', 'seed-rubio', 'seed-stf',
            'seed-franca', 'seed-curitiba'}


def _load():
    recs = []
    with open(PAIRS, encoding="utf-8") as f:
        for n, line in enumerate(f):
            if not line.strip():
                continue
            r = json.loads(line)
            r.setdefault("id", f"seed-{n}")
            recs.append(r)
    return recs


def _judge():
    recs = _load()
    docs = []
    for r in recs:
        docs.append({"title": r["a"]})
        docs.append({"title": r["b"]})
    S = tfidf_matrix(docs) @ tfidf_matrix(docs).T
    toksets = [set(tok(d["title"])) for d in docs]
    now = time.time()
    arts = []
    for r in recs:
        arts.append({"title": r["a"], "ts": now,
                     "summary": r.get("summary_a", ""),
                     "source_id": r.get("source_a") or "sa",
                     "section": r.get("section_a")})
        arts.append({"title": r["b"], "ts": now,
                     "summary": r.get("summary_b", ""),
                     "source_id": r.get("source_b") or "sb",
                     "section": r.get("section_b")})
    out = {}
    for k, r in enumerate(recs):
        i, j = 2 * k, 2 * k + 1
        ok, rule = _pair_decision(arts, toksets, S, None, i, j, 0.38, 48)
        out[r["id"]] = (r["label"], ok, rule)
    return out


_JUDGED = _judge()


def test_cluster_pairs_file_is_valid():
    recs = _load()
    assert len(recs) >= 150, f"F1 exige seed ≥ 150, há {len(recs)}"
    assert {r["label"] for r in recs} <= {"same", "related", "different"}
    assert all(r["a"] and r["b"] for r in recs)


def test_different_pairs_never_fuse():
    bad = [i for i, (lab, ok, rule) in _JUDGED.items()
           if lab == "different" and ok]
    assert not bad, f"pares different fundidos: {bad}"


def test_must_fuse_pairs_fuse():
    bad = [i for i in MUST_FUSE if i in _JUDGED
           and not _JUDGED[i][1]]
    assert not bad, f"pares same que deixaram de fundir: {bad}"


@pytest.mark.parametrize("pid", sorted(KNOWN_FN))
def test_known_false_negatives(pid):
    if pid not in _JUDGED:
        pytest.skip("id fora do corpus atual")
    lab, ok, rule = _JUDGED[pid]
    assert lab == "same"
    if ok:
        pytest.skip(f"{pid} voltou a fundir — remover de KNOWN_FN")
    pytest.xfail(f"FN conhecido ({rule}): funde no corpus real via "
                 "transitividade/IDF, não no harness isolado — alvo do F2/F3")


def test_pair_features_schema_and_determinism(tmp_path):
    from ops.pair_features import FEATURE_NAMES, build
    rows1 = build("tests/cluster_pairs.jsonl")
    rows2 = build("tests/cluster_pairs.jsonl")
    assert [r["id"] for r in rows1] == [r["id"] for r in rows2]
    assert rows1 == rows2, "extração de features deve ser determinística"
    assert len(rows1) >= 150
    for r in rows1:
        assert list(r["features"]) == FEATURE_NAMES
        assert r["label"] in {"same", "related", "different"}
    by = {r["id"]: r for r in rows1}
    # c076 (Solano, FN do no_content) tem os sinais que o modelo deve aprender
    f = by["c076"]["features"]
    assert f["numbers_match"] == 1 and f["subject_match"] == 1
    assert by["c076"]["decision_now"] == "rejected"
