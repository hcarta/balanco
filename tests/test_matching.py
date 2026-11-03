"""Matching história x checagem, bucket de viés, alertas e clustering básico."""
import time

import app
from app import attach_checks, bucket, build_idf, claim_overlap, cluster, store_alerts, tok

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
    """Fase 2: 5 faixas (L/CL/C/CR/R) com bordas -0.8/-0.3/0.3/0.8."""
    assert bucket(-1.6) == "L"
    assert bucket(-0.8) == "L"
    assert bucket(-0.5) == "CL"
    assert bucket(-0.3) == "CL"
    assert bucket(-0.2) == "C"
    assert bucket(0.0) == "C"
    assert bucket(0.2) == "C"
    assert bucket(0.3) == "CR"
    assert bucket(0.5) == "CR"
    assert bucket(0.8) == "R"
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


def test_attach_checks_includes_terms():
    stories = [{
        "id": "s000", "title": "Governo Lula bloqueou Gás do Povo e Bolsa Família após eleições",
        "articles": [
            {"title": "Governo Lula bloqueou Gás do Povo após eleições",
             "link": "https://x/1", "source": "V", "source_id": "v"},
        ],
    }]
    checks = [{
        "title": "É FAKE que governo Lula bloqueou Gás do Povo e Bolsa Família",
        "link": "https://c/1", "checker": "Lupa", "published": "2026-10-30T00:00:00+00:00",
        "verdict": "falso", "label": "Falso",
    }]
    out, ledger, matches = attach_checks(stories, checks)
    assert out[0]["checks"], "era esperado ao menos um casamento"
    assert set(out[0]["checks"][0]["terms"]) <= {"governo", "lula", "bloqueou", "gás", "povo", "bolsa", "família", "eleições"}
    assert len(out[0]["checks"][0]["terms"]) >= 2
    assert matches and matches[0]["terms"]


def test_archive_snapshot_and_prune(tmp_path):
    import datetime as _dt
    import json as _json
    from app import archive_snapshot
    site = tmp_path / "site"
    site.mkdir()
    for day in ["2026-10-28", "2026-10-29", "2026-10-30"]:
        (site / "arquivo").mkdir(exist_ok=True)
        (site / "arquivo" / f"{day}.json").write_text(
            _json.dumps({"n_stories": 1, "generated_at": day}))
    import app as _app
    old_keep = _app.ARCHIVE_KEEP
    _app.ARCHIVE_KEEP = 2
    try:
        archive_snapshot(str(site), {"n_stories": 5})
    finally:
        _app.ARCHIVE_KEEP = old_keep
    import glob as _glob
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    expected = sorted(["2026-10-28", "2026-10-29", "2026-10-30", today])[-2:]
    got = sorted(_glob.glob(str(site / "arquivo" / "????-??-??.json")))
    assert [g[-15:-5] for g in got] == expected
    assert (site / "arquivo" / "index.html").exists()


def test_write_feed_is_valid_rss(tmp_path):
    import xml.etree.ElementTree as ET
    from app import write_feed
    stories = [{
        "id": "s001", "title": "Teste & manchete <ok>",
        "summary": "Resumo.", "updated": "2026-10-30T00:00:00+00:00",
        "counts": {"total": 3}, "pct": {"L": 33, "C": 34, "R": 33},
    }]
    dest = write_feed(str(tmp_path), stories)
    root = ET.parse(dest).getroot()
    assert root.tag == "rss"
    items = root.find("channel").findall("item")
    assert len(items) == 1
    assert items[0].find("link").text.endswith("?story=s001")


def test_entity_match_rejects_generic_only():
    from app import entity_match, entities
    story = entities("Chineses acusados de espionagem são condenados à prisão nos Estados Unidos")
    bts = entities("O que faz o BTS arrastar multidões de fãs pelo Brasil")
    ok, _ = entity_match(story, bts)
    assert not ok, "BTS não tem nada com espionagem chinesa (só 'estados/unidos' em comum)"


def test_entity_match_keeps_specific():
    from app import entity_match, entities
    a = entities("Governo Lula convoca representante da Argentina sobre a saída de Flávio Bolsonaro")
    b = entities("O usurpador: Flávio Bolsonaro sequestrou o discurso anticorrupção")
    ok, terms = entity_match(a, b)
    assert ok and "flávio bolsonaro" in terms


def _lf_article(title, src="piaui", link="https://x/lr", summary="", ts=None):
    names = {"piaui": "piauí", "nexo": "Nexo Jornal", "oeste": "Revista Oeste"}
    return {"source_id": src, "source_name": names.get(src, src),
            "title": title, "link": link, "summary": summary,
            "published": "2026-10-31T00:00:00+00:00",
            "ts": time.time() if ts is None else ts}


def test_longreads_excludes_non_journalism():
    from app import attach_longreads, entities, entity_match
    story = {"id": "s1", "title": "BTS faz show em São Paulo e mobiliza fãs",
             "articles": [{"source": "G1"}], "counts": {"total": 2}}
    bad = [
        "Oeste Sem Filtro: assista ao programa sobre o BTS em São Paulo",
        "Palavras Cruzadas do 'Nexo': o BTS e São Paulo",
    ]
    good = "Análise: por que o BTS lota estádios em São Paulo"
    arts = [_lf_article(bad[0], src="oeste", link="https://x/prog"),
            _lf_article(bad[1], src="nexo", link="https://x/quiz"),
            _lf_article(good, link="https://x/ok")]
    # garante que o teste não passa por "não casou": os 3 casam no tópico
    for t in bad + [good]:
        ok, _ = entity_match(entities(story["title"]), entities(t))
        assert ok, f"fixture inválida: '{t}' não casa no tópico"
    out = attach_longreads([story], arts, {"piaui", "oeste", "nexo"})
    titles = [lr["title"] for lr in out[0]["longreads"]]
    assert good in titles
    assert not any(t in titles for t in bad), f"não-jornalismo vazou: {titles}"


def test_longreads_redundant_source_only_if_analysis():
    from app import attach_longreads
    # Nexo já cobre a história; peça comum não entra, análise sim
    stories = [{"id": "s1", "title": "Flávio Bolsonaro fala pela 1ª vez dos EUA",
                "articles": [{"source": "Nexo Jornal"}, {"source": "G1"}],
                "counts": {"total": 2}}]
    arts = [
        _lf_article("Flávio Bolsonaro fala pela 1ª vez dos EUA", src="nexo",
                    link="https://x/n1"),
        _lf_article("Análise: por que a fuga de Flávio Bolsonaro muda o jogo",
                    src="nexo", link="https://x/n2"),
    ]
    out = attach_longreads(stories, arts, {"nexo"})
    titles = [lr["title"] for lr in out[0]["longreads"]]
    assert "Análise: por que a fuga de Flávio Bolsonaro muda o jogo" in titles
    assert "Flávio Bolsonaro fala pela 1ª vez dos EUA" not in titles


def test_longreads_one_per_source():
    from app import attach_longreads
    stories = [{"id": "s1", "title": "Fuga de Flávio Bolsonaro para os EUA",
                "articles": [{"source": "G1"}, {"source": "Folha"}],
                "counts": {"total": 3}}]
    arts = [
        _lf_article("A fuga de Flávio Bolsonaro e o voo cego", src="piaui",
                    link="https://x/a"),
        _lf_article("Flávio Bolsonaro: o usurpador", src="piaui", link="https://x/b"),
        _lf_article("Análise: a fuga de Flávio Bolsonaro e o Congresso", src="nexo",
                    link="https://x/c"),
    ]
    out = attach_longreads(stories, arts, {"piaui", "nexo"})
    srcs = [lr["source"] for lr in out[0]["longreads"]]
    assert len(srcs) == len(set(srcs)), f"fonte repetida: {srcs}"


def test_diversify_longreads_keeps_best_owner():
    from app import diversify_longreads
    s_big = {"id": "s1", "title": "Governo Lula convoca a Argentina sobre Flávio Bolsonaro",
             "counts": {"total": 9}, "updated": "2026-10-31T10:00:00+00:00",
             "longreads": [{"link": "https://x/p", "source": "Nexo", "title": "P", "terms": ["a"]}]}
    s_small = {"id": "s2", "title": "Trump e a fuga de Flávio Bolsonaro",
               "counts": {"total": 2}, "updated": "2026-10-31T11:00:00+00:00",
               "longreads": [{"link": "https://x/p", "source": "Nexo", "title": "P", "terms": ["a"]},
                             {"link": "https://x/q", "source": "piauí", "title": "Q", "terms": ["b"]}]}
    out = diversify_longreads([s_big, s_small])
    assert out[0]["longreads"] and out[0]["longreads"][0]["link"] == "https://x/p"
    links = [lr["link"] for lr in out[1]["longreads"]]
    assert "https://x/p" not in links and "https://x/q" in links


def test_diversify_longreads_no_duplicate_fallback():
    from app import diversify_longreads
    big = {"id": "s1", "counts": {"total": 9}, "updated": "2026-10-31T10:00:00+00:00",
           "longreads": [{"link": "https://x/p", "source": "Nexo", "title": "P", "terms": []}]}
    small = {"id": "s2", "counts": {"total": 2}, "updated": "2026-10-31T11:00:00+00:00",
             "longreads": [{"link": "https://x/p", "source": "Nexo", "title": "P", "terms": []}]}
    out = diversify_longreads([big, small])
    assert [lr["link"] for lr in out[0]["longreads"]] == ["https://x/p"]
    assert out[1]["longreads"] == [], "peça de outra história não pode ser reposta"


# ── F2: consolidação de mesmo fato + pautas ────────────────────────────────
def _story(sid, title, arts, updated="2026-10-31T10:00:00+00:00"):
    items = [{"source": src, "title": t, "link": f"https://x/{sid}/{i}",
              "bias": b, "bucket": bk, "summary": ""}
             for i, (src, t, b, bk) in enumerate(arts)]
    return {"id": sid, "title": title, "summary": "", "articles": items,
            "counts": {"L": 0, "C": 0, "R": 0, "total": len(items)},
            "pct": {"L": 0, "C": 0, "R": 0}, "avg_bias": 0.0,
            "blindspot": None, "updated": updated}


def test_consolidate_merges_same_fact():
    from app import consolidate
    a = _story("s1", "Governo Lula convoca representante da Argentina para pedir explicações sobre fuga de Flávio Bolsonaro",
               [("G1", "Governo Lula convoca representante da Argentina para pedir explicações sobre fuga de Flávio Bolsonaro", 0, "C"),
                ("Folha", "Itamaraty chama embaixador argentino para tratar da fuga de Flávio Bolsonaro", -0.5, "L")])
    b = _story("s2", "Brasil diz ter convocado diplomata argentina para cobrar explicações sobre viagem de Flávio Bolsonaro",
               [("UOL", "Brasil diz ter convocado diplomata argentina para cobrar explicações sobre viagem de Flávio Bolsonaro", 0, "C"),
                ("CNN", "Brasil cobra explicações da Argentina sobre a viagem de Flávio Bolsonaro", 0, "C")])
    out = consolidate([a, b])
    assert len(out) == 1, "mesmo fato deveria virar uma história"
    assert out[0]["counts"]["total"] == 4
    assert len(out[0]["developments"]) == 1


def test_consolidate_rejects_same_person_different_fact():
    from app import consolidate
    # ambos citam Flávio Bolsonaro em alguma matéria, mas são fatos distintos
    a = _story("s1", "Rubio e Vieira conversam e marcam reunião bilateral",
               [("G1", "Rubio e Vieira conversam e marcam reunião bilateral", 0, "C"),
                ("Folha", "Reunião bilateral após a fuga de Flávio Bolsonaro", -0.5, "L")])
    b = _story("s2", "Trump e Milei enfrentam pressão por fuga de Flávio Bolsonaro",
               [("UOL", "Trump e Milei enfrentam pressão por fuga de Flávio Bolsonaro", 0, "C")])
    out = consolidate([a, b])
    assert len(out) == 2, "entidade em comum não basta: são fatos diferentes"


def test_consolidate_rejects_place_name_coincidence():
    from app import consolidate
    a = _story("s1", "Ministros vão ao Mato Grosso do Sul para investigar violência política",
               [("G1", "Ministros vão ao Mato Grosso do Sul para investigar violência política", 0, "C")])
    b = _story("s2", "Presidente do TCE de Mato Grosso sacou R$ 15 milhões em dinheiro na boca do caixa",
               [("UOL", "Presidente do TCE de Mato Grosso sacou R$ 15 milhões em dinheiro", 0.5, "R")])
    out = consolidate([a, b])
    assert len(out) == 2, "'Mato Grosso' é lugar, não prova de mesmo fato"


def test_consolidate_recomputes_counts_and_blindspot():
    from app import consolidate
    a = _story("s1", "Binance sofre ataque hacker de US$ 6,3 bilhões",
               [("G1", "Binance sofre ataque hacker de US$ 6,3 bilhões", 1.0, "R"),
                ("UOL", "Binance sofre ataque hacker de US$ 6,3 bilhões: Coreia do Norte é suspeita", 1.0, "R")])
    b = _story("s2", "Ataque à Binance: hackers norte-coreanos de criptomoedas estão entre os suspeitos",
               [("CNN", "Ataque à Binance: hackers norte-coreanos de criptomoedas estão entre os suspeitos", 1.0, "R"),
                ("Folha", "Hackers da Coreia do Norte roubam US$ 6,3 bilhões da Binance", 1.0, "R")])
    out = consolidate([a, b])
    assert len(out) == 1
    s = out[0]
    assert s["counts"]["L"] == 0
    assert s["counts"]["C"] == 0
    assert s["counts"]["R"] == 4
    assert s["counts"]["total"] == 4
    assert s["counts"]["independent"] == 4
    g = s["counts"]["groups"]
    assert g["R"] == 4 and sum(g[b] for b in app.BUCKETS) == 4
    assert s["blindspot"] == "left", "4 grupos de direita e nenhum de esquerda"


def test_attach_hubs_groups_narrative_without_merging():
    from app import attach_hubs
    def st(sid, t):
        return _story(sid, t, [("G1", t, 0, "C")])
    stories = [st("s1", "Flávio Bolsonaro fala pela 1ª vez dos EUA"),
               st("s2", "Trump e a fuga de Flávio Bolsonaro"),
               st("s3", "Como aliados reagem ao golpismo de Flávio Bolsonaro"),
               st("s4", "Conta de luz segue com bandeira verde em novembro")]
    out = attach_hubs(stories)
    assert out[0]["hub"]["key"] == "flávio bolsonaro"
    assert out[0]["hub"]["size"] == 3
    assert out[0]["hub"]["label"] == "Flávio Bolsonaro"
    assert out[3]["hub"] is None, "pauta exige 3+ histórias do mesmo nome próprio"
    assert len(out) == 4, "pauta não funde histórias"


def _legacy_cluster(articles, thresh=0.38, window_h=48):
    """Implementação anterior (O(n²) em Python), só para equivalência."""
    n = len(articles)
    X = app.tfidf_matrix(articles)
    S = X @ X.T
    toksets = [set(app.tok(a["title"])) for a in articles]
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            shared = toksets[i] & toksets[j]
            if len(shared) < 1:
                continue
            pred = S[i, j] >= thresh and len(shared) >= 2
            if not pred:
                continue
            si, sj = articles[i].get("source_id"), articles[j].get("source_id")
            if si is not None and si == sj:
                ti, tj = app.tok(articles[i]["title"]), app.tok(articles[j]["title"])
                if len(ti) >= 2 and len(tj) >= 2 and ti[:2] == tj[:2]:
                    continue
                same_sec = bool(articles[i].get("section")) and \
                    articles[i].get("section") == articles[j].get("section")
                floor = thresh + (0.12 if same_sec else 0.10)
                if S[i, j] < floor or len(shared) < 3:
                    continue
            dt = abs(articles[i]["ts"] - articles[j]["ts"]) / 3600
            w = app.pair_window(articles[i].get("section"),
                                articles[j].get("section"), window_h)
            if dt <= w:
                union(i, j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=lambda g: (-len(g),
                                                  -max(articles[i]["ts"] for i in g)))


def test_vectorized_cluster_matches_reference():
    now = time.time()
    arts = [
        {"title": "Senado aprova marco fiscal em votação apertada", "ts": now,
         "section": "politica", "source_id": "a"},
        {"title": "Senado aprova marco fiscal em votação apertada no plenário",
         "ts": now, "section": "politica", "source_id": "b"},
        {"title": "Itamaraty convoca diplomata argentina para explicar fuga de Flávio",
         "ts": now, "section": "politica", "source_id": "c"},
        {"title": "Itamaraty convoca diplomata argentina para explicar fuga de senador",
         "ts": now, "section": "politica", "source_id": "d"},
        {"title": "Festival de cinema exibe filmes nacionais premiados", "ts": now,
         "section": "cultura", "source_id": "e"},
        {"title": "Pinguins vencem clássico no gelo", "ts": now,
         "section": "esporte", "source_id": "f"},
        {"title": "Pinguins vencem clássico no gelo em prorrogação", "ts": now,
         "section": "esporte", "source_id": "f"},
        {"title": "Senado aprova marco fiscal em votação apertada",
         "ts": now - 30 * 3600, "section": "politica", "source_id": "g"},
        {"title": "Crítica teatral: a nova montagem de Hamlet no municipal",
         "ts": now, "section": "vozes", "source_id": "h"},
        {"title": "Crítica teatral: nova montagem de Hamlet em cartaz no municipal",
         "ts": now - 5 * 86400, "section": "vozes", "source_id": "i"},
    ]
    new = {frozenset(g) for g in cluster(arts)}
    old = {frozenset(g) for g in _legacy_cluster(arts)}
    assert new == old


def test_coherence_splits_a_chain_group():
    """F-04: um grupo single-link com dois fatos vira dois grupos."""
    import numpy as np
    now = time.time()
    arts = [{"title": f"Notícia {i}", "ts": now, "source_id": f"s{i}",
             "section": "politica"} for i in range(20)]
    toksets = [{"a1", "a2", "a3"} if i < 10 else {"b1", "b2", "b3"}
               for i in range(20)]
    S = np.full((20, 20), 0.1, dtype="float32")
    S[:10, :10] = 0.8
    S[10:, 10:] = 0.8
    np.fill_diagonal(S, 1.0)
    out = app._cohere([list(range(20))], arts, toksets, S, None, 48)
    assert sorted(len(g) for g in out) == [10, 10]
    assert not any(0 in g and 10 in g for g in out)


def test_excluded_title_filters_service_but_not_news():
    assert app.excluded_title("VÍDEOS: AB1 de sábado, 31 de outubro de 2026")
    assert app.excluded_title("Jornal da Noite ao vivo: acompanhe a edição de hoje")
    assert app.excluded_title("Veja o resultado da Quina concurso 7156 desta sexta-feira")
    assert app.excluded_title(
        "Dia de Finados: cemitérios de São José dos Campos esperam 50 mil visitantes")
    assert app.excluded_title(
        "RN terá bandeira verde nas contas de energia em novembro de 2026")
    # notícia sobre o feriado não é serviço
    assert not app.excluded_title("Ataque durante o Dia de Finados deixa dois feridos")


def test_slim_payload_drops_heavy_fields():
    p = {"generated_at": "x", "n_stories": 1,
         "sources": [{"id": "a"}], "factchecks": [{"title": "c"}],
         "stories": [{"id": "h1", "title": "t", "counts": {"total": 2},
                      "articles": [{"source": "A", "title": "a",
                                    "link": "l", "bucket": "C", "bias": 0,
                                    "image": "x", "ownership": "y"}]}]}
    s = app._slim_payload(p)
    assert "sources" not in s and "factchecks" not in s
    assert s["stories"][0]["articles"][0] == {
        "source": "A", "title": "a", "link": "l", "bucket": "C", "bias": 0}


def test_section_labels_hide_generic_and_language_paths():
    assert app.section_label("Geral") == ""
    assert app.section_label("Pt-br") == ""
    assert app.section_label("Pop") == "Cultura"
    assert app.section_label("Política") == "Política"


def test_blindspot_three_vehicles():
    """Caso França (31/10): 1 esquerda, 2 centro, 0 direita = blindspot de direita."""
    assert app.blindspot_of(1, 2, 0) == "right"
    assert app.blindspot_of(0, 2, 1) == "left"
    assert app.blindspot_of(0, 3, 0) is None  # só centro não é blindspot
    assert app.blindspot_of(1, 1, 0) is None  # 2 veículos: cedo demais
    assert app.blindspot_of(0, 1, 1) is None


def test_build_marks_three_vehicle_right_blindspot():
    """Integração: 1 esquerda + 2 centro + 0 direita => blindspot de direita."""
    now = time.time()
    title = "Protestos na França reúnem 320 mil pessoas, diz governo"
    srcs = [
        {"id": "b247", "name": "Brasil 247", "bias": -1.0, "factuality": "mixed",
         "ownership": "independente"},
        {"id": "folha", "name": "Folha", "bias": 0.0, "factuality": "high",
         "ownership": "familia"},
        {"id": "oglobo", "name": "O Globo", "bias": 0.0, "factuality": "high",
         "ownership": "globo"},
    ]
    arts = [{
        "title": title, "link": f"https://x/{i}", "source_id": s["id"],
        "source_name": s["name"], "base_bias": s["bias"], "ts": now,
        "published": "2026-10-31T12:00:00+00:00", "section": "mundo",
        "summary": "", "first_seen": "2026-10-31T12:00:00+00:00",
    } for i, s in enumerate(srcs)]
    out = app.build(srcs, arts, {})
    assert len(out) == 1
    assert out[0]["counts"]["L"] == 1
    assert out[0]["counts"]["C"] == 2
    assert out[0]["counts"]["R"] == 0
    assert out[0]["counts"]["total"] == 3
    assert out[0]["counts"]["independent"] == 3
    g = out[0]["counts"]["groups"]
    assert g["L"] == 1 and g["C"] == 2 and g["CL"] == g["CR"] == g["R"] == 0
    assert out[0]["blindspot"] == "right"


def test_independent_counts_collapses_same_owner():
    arts = [
        {"source_id": "g1", "group": "globo", "bias": 0.0, "bucket": "C"},
        {"source_id": "oglobo", "group": "globo", "bias": 0.1, "bucket": "C"},
        {"source_id": "folha", "group": "folha", "bias": -0.6, "bucket": "L"},
        {"source_id": "uol", "group": "uol", "bias": 0.0, "bucket": "C"},
    ]
    gc, ind, avg = app.independent_counts(arts, "bias")
    assert gc["CL"] == 1 and gc["C"] == 2 and gc["L"] == gc["CR"] == gc["R"] == 0
    assert ind == 3


def test_build_requires_two_independent_groups_and_counts_them():
    now = time.time()
    title = "Senado aprova marco fiscal em votação apertada"
    srcs = [
        {"id": "g1", "name": "G1", "group": "globo", "bias": 0.0,
         "factuality": "high", "ownership": "conglomerado"},
        {"id": "oglobo", "name": "O Globo", "group": "globo", "bias": 0.1,
         "factuality": "high", "ownership": "conglomerado"},
        {"id": "folha", "name": "Folha", "group": "folha", "bias": -0.6,
         "factuality": "high", "ownership": "familia"},
    ]
    arts = [{
        "title": title, "link": f"https://x/{s['id']}", "source_id": s["id"],
        "source_name": s["name"], "base_bias": s["bias"], "ts": now,
        "published": "2026-10-31T12:00:00+00:00", "section": "politica",
        "summary": "", "first_seen": "2026-10-31T12:00:00+00:00",
    } for s in srcs]
    out = app.build(srcs, arts, {})
    assert len(out) == 1
    assert out[0]["counts"]["total"] == 3
    assert out[0]["counts"]["independent"] == 2
    g = out[0]["counts"]["groups"]
    assert g["CL"] == 1 and g["C"] == 1
    assert out[0]["pct"]["CL"] == 50 and out[0]["pct"]["C"] == 50

    # só Globo (G1 + O Globo) não é uma história entre veículos independentes
    out2 = app.build(srcs[:2], arts[:2], {})
    assert out2 == []


def test_representative_prefers_medoid_and_clean_title():
    items = [
        {"title": "Senado aprova marco fiscal em votação apertada",
         "source_id": "a"},
        {"title": "Senado aprova marco fiscal em votação apertada no plenário",
         "source_id": "b"},
        {"title": "VOCÊ NÃO VAI ACREDITAR: Senado aprova marco fiscal?!",
         "source_id": "c"},
    ]
    meta = {k: {"factuality": "high"} for k in ("a", "b", "c")}
    rep = app._representative(items, meta)
    assert "Senado aprova marco fiscal" in rep["title"]
    assert "VOCÊ NÃO" not in rep["title"]
    assert app._clean_title("Senado aprova marco fiscal - G1") == \
        "Senado aprova marco fiscal"
    assert app._clean_title("VÍDEOS: Jornal da Noite") == "Jornal da Noite"


def test_representative_avoids_opinion_blog():
    items = [
        {"title": "Flávio Bolsonaro submete a direita ao vexame com fuga e carta golpista",
         "source_id": "oglobo", "section": "blogs"},
        {"title": "Valdemar diz que não gostou de carta golpista publicada por Flávio Bolsonaro",
         "source_id": "folha", "section": "politica"},
        {"title": "Aliados rejeitam tom golpista de carta de Flávio Bolsonaro",
         "source_id": "g1", "section": "politica"},
    ]
    meta = {k: {"factuality": "high"} for k in ("oglobo", "folha", "g1")}
    rep = app._representative(items, meta)
    assert "vexame" not in rep["title"]
    assert "Flávio Bolsonaro" in rep["title"]


def test_piece_kind_classifies_urls_titles_and_sources():
    pk = app.piece_kind
    assert pk({"link": "https://x/opiniao/foo", "title": "Notícia"}) == "opinion"
    assert pk({"link": "https://x/podcast/foo", "title": "Notícia"}) == "podcast"
    assert pk({"link": "https://x/video/foo", "title": "Notícia"}) == "video"
    assert pk({"link": "https://x/ao-vivo/foo", "title": "Notícia"}) == "live"
    assert pk({"link": "https://x/n", "title": "Análise: o que muda"}) == "analysis"
    assert pk({"link": "https://x/n", "title": "Entrevista com o ministro"}) == "interview"
    assert pk({"link": "https://x/n", "title": "Entenda a proposta"}) == "explainer"
    assert pk({"link": "https://x/n", "title": "Notícia", "section": "opiniao"}) == "opinion"
    assert pk({"link": "https://x/n", "title": "Notícia"},
              {"longform": True}) == "longform"
    assert pk({"link": "https://x/n", "title": "Notícia",
               "section": "politica"}) == "hard_news"


def test_build_counts_only_coverage_kinds():
    now = time.time()
    title = "Protestos na França reúnem 320 mil pessoas, diz governo"
    srcs = [
        {"id": "l", "name": "Esquerda", "bias": -1.0, "factuality": "high",
         "ownership": "independente"},
        {"id": "c1", "name": "Centro 1", "bias": 0.0, "factuality": "high",
         "ownership": "familia"},
        {"id": "c2", "name": "Centro 2", "bias": 0.0, "factuality": "high",
         "ownership": "globo"},
        {"id": "r", "name": "Direita", "bias": 1.0, "factuality": "mixed",
         "ownership": "independente"},
    ]
    arts = [{
        "title": title, "link": f"https://x/{s['id']}", "source_id": s["id"],
        "source_name": s["name"], "base_bias": s["bias"], "ts": now,
        "published": "2026-10-31T12:00:00+00:00",
        "section": "opiniao" if s["id"] == "r" else "mundo",
        "summary": "", "first_seen": "2026-10-31T12:00:00+00:00",
    } for s in srcs]
    out = app.build(srcs, arts, {})
    assert len(out) == 1
    s = out[0]
    assert s["counts"]["total"] == 3
    assert s["counts"]["frames"] == 1
    assert s["counts"]["articles"] == 4
    g = s["counts"]["groups"]
    assert g["L"] == 1 and g["C"] == 2 and g["R"] == 0
    assert s["counts"]["independent"] == 3
    assert s["blindspot"] == "right"
    assert s["pct"]["L"] == 33 and s["pct"]["C"] == 67 and s["pct"]["R"] == 0
    op = [a for a in s["articles"] if a["source_id"] == "r"][0]
    assert op["piece_kind"] == "opinion"


def test_longreads_background_requires_two_entities():
    from app import attach_longreads
    story = {"id": "s1",
             "title": "Nunes Marques e Mendonça tentam se afastar de Flávio Bolsonaro",
             "articles": [{"source": "G1"}], "counts": {"total": 2}}
    old = time.time() - 30 * 86400
    two = _lf_article("Nunes Marques e Mendonça: o que muda no TSE",
                      src="piaui", link="https://x/two", ts=old)
    one = _lf_article("Flávio Bolsonaro foge para os EUA",
                      src="nexo", link="https://x/one", ts=old)
    out = attach_longreads([story], [two, one], {"piaui", "nexo"})
    lr = out[0]["longreads"]
    assert any(x["link"] == "https://x/two" and x["relation"] == "background"
               for x in lr)
    assert not any(x["link"] == "https://x/one" for x in lr)


def test_longreads_recent_is_same_relation():
    from app import attach_longreads
    story = {"id": "s1",
             "title": "Nunes Marques e Mendonça tentam se afastar de Flávio Bolsonaro",
             "articles": [{"source": "G1"}], "counts": {"total": 2}}
    piece = _lf_article("Nunes Marques e Mendonça: o que muda no TSE",
                        src="piaui", link="https://x/r")
    out = attach_longreads([story], [piece], {"piaui"})
    assert out[0]["longreads"][0]["relation"] == "same"


def test_longreads_background_uses_dek():
    from app import attach_longreads
    story = {"id": "s1", "title": "Fachin devolve caso INSS a Mendonça",
             "articles": [{"source": "G1"}], "counts": {"total": 2}}
    old = time.time() - 30 * 86400
    piece = _lf_article(
        "O instituto de Mendonça", src="piaui", link="https://x/dek",
        summary="Como André Mendonça transformou o Master e o INSS em plataforma eleitoral",
        ts=old)
    out = attach_longreads([story], [piece], {"piaui"})
    lr = out[0]["longreads"]
    assert lr and lr[0]["relation"] == "background"
    assert "mendonça" in lr[0]["why"]


def test_build_timeline_orders_by_first_seen():
    now = time.time()
    title = "Senado aprova marco fiscal em votação apertada"
    srcs = [
        {"id": "a", "name": "A", "bias": -0.6, "factuality": "high",
         "ownership": "independente"},
        {"id": "b", "name": "B", "bias": 0.0, "factuality": "high",
         "ownership": "familia"},
        {"id": "c", "name": "C", "bias": 0.6, "factuality": "high",
         "ownership": "globo"},
    ]
    times = ["2026-10-31T10:00:00+00:00", "2026-10-31T10:05:00+00:00",
             "2026-10-31T10:02:00+00:00"]
    seen = ["2026-10-31T10:10:00+00:00", "2026-10-31T10:06:00+00:00",
            "2026-10-31T10:03:00+00:00"]
    arts = [{
        "title": title, "link": f"https://x/{s['id']}", "source_id": s["id"],
        "source_name": s["name"], "base_bias": s["bias"], "ts": now,
        "published": times[i], "first_seen": seen[i], "section": "politica",
        "summary": "",
    } for i, s in enumerate(srcs)]
    out = app.build(srcs, arts, {})
    assert len(out) == 1
    assert [x["source"] for x in out[0]["timeline"]] == ["A", "C", "B"]


def test_representative_prefers_recent_among_central():
    items = [
        {"title": "Binance sofre ataque hacker de US$ 6,3 bilhões",
         "source_id": "a", "section": "tecnologia",
         "published": "2026-10-31T13:00:00+00:00"},
        {"title": "Binance diz ter coberto 90% das perdas após ataque hacker",
         "source_id": "b", "section": "tecnologia",
         "published": "2026-11-01T12:00:00+00:00"},
        {"title": "Binance suspende saques após ataque hacker",
         "source_id": "c", "section": "tecnologia",
         "published": "2026-11-01T10:00:00+00:00"},
    ]
    meta = {k: {"factuality": "high"} for k in ("a", "b", "c")}
    rep = app._representative(items, meta)
    assert rep["published"].startswith("2026-11-01")


def test_build_updated_ignores_frames():
    title = "Binance retoma saques após ataque hacker"
    srcs = [
        {"id": "l", "name": "L", "bias": -0.6, "factuality": "high",
         "ownership": "independente"},
        {"id": "c", "name": "C", "bias": 0.0, "factuality": "high",
         "ownership": "familia"},
        {"id": "r", "name": "R", "bias": 0.6, "factuality": "mixed",
         "ownership": "globo"},
    ]
    arts = [
        {"title": title, "link": "https://x/l", "source_id": "l",
         "source_name": "L", "base_bias": -0.6, "ts": 1.0,
         "published": "2026-10-31T13:00:00+00:00",
         "first_seen": "2026-10-31T13:10:00+00:00", "section": "economia",
         "summary": ""},
        {"title": title, "link": "https://x/c", "source_id": "c",
         "source_name": "C", "base_bias": 0.0, "ts": 1.0,
         "published": "2026-10-31T13:00:00+00:00",
         "first_seen": "2026-10-31T13:10:00+00:00", "section": "economia",
         "summary": ""},
        {"title": title, "link": "https://x/r", "source_id": "r",
         "source_name": "R", "base_bias": 0.6, "ts": 1.0,
         "published": "2026-11-01T13:00:00+00:00",
         "first_seen": "2026-11-01T13:10:00+00:00", "section": "opiniao",
         "summary": ""},
    ]
    out = app.build(srcs, arts, {})
    assert len(out) == 1
    assert out[0]["counts"]["frames"] == 1
    assert out[0]["updated"].startswith("2026-10-31T13:00")


def test_excluded_title_filters_weather_not_market():
    assert app.excluded_title("Novembro em SP começa com chuva e calor; veja previsão completa")
    assert not app.excluded_title("Previsão do mercado para o próximo trimestre")


def test_excluded_title_filters_payment_calendars():
    service = [
        "Calendário do Bolsa Família: confira a data de pagamento para novembro",
        "Bolsa Família de novembro: veja o calendário de pagamentos",
        "Calendário do INSS: datas de pagamento por final de benefício",
        "FGTS: calendário de saque e pagamento em novembro",
    ]
    news = [
        "Governo antecipa pagamento do Bolsa Família em novembro",
        "Bolsa Família terá novo valor em 2027, diz ministro",
        "INSS divulga reajuste de benefícios acima da inflação",
    ]
    assert all(app.excluded_title(t) for t in service)
    assert not any(app.excluded_title(t) for t in news)


def test_weather_forecast_out_but_impact_stays():
    forecasts = [
        "Novembro começa com calor e pancadas de chuva em São Paulo",
        "Volta a chover em São Paulo? Veja a previsão para os próximos dias",
        "Inmet emite alerta de tempestade para Apucarana e região",
        "Fim de semana terá temporais em parte do Brasil",
        "Novembro terá chuvas acima da média e gangorra nas temperaturas",
    ]
    impact = [
        "Chuva forte provoca alagamentos e deixa moradores ilhados em Santo Antônio de Pádua",
        "Temporal deixa três mortos e 200 desabrigados no Sul",
        "Previsão do mercado para o próximo trimestre",
    ]
    assert all(app.excluded_title(t) for t in forecasts)
    assert not any(app.excluded_title(t) for t in impact)


def test_cluster_needs_entity_anchor_not_topic_words():
    """Caso real: 'eleição presidencial' ligava a Bulgária ao Flávio Bolsonaro."""
    now = time.time()
    arts = [
        {"title": "Bulgária: eleição presidencial traz visões opostas sobre Rússia e guerra na Ucrânia",
         "ts": now, "source_id": "uol", "section": "mundo"},
        {"title": "A eleição presidencial: 3 observações e uma sugestão",
         "ts": now, "source_id": "oeste", "section": "vozes"},
        {"title": "Flávio Bolsonaro admite disputar nova eleição presidencial antes de 2030",
         "ts": now, "source_id": "istoe", "section": "politica"},
        {"title": "Nos EUA, Flávio fala em disputar eleição antes de 2030",
         "ts": now, "source_id": "sbt", "section": "politica"},
    ]
    groups = cluster(arts)
    assert len(groups) == 3, [sorted(g) for g in groups]
    for g in groups:
        titles = " ".join(arts[i]["title"].lower() for i in g)
        assert not ("bulgária" in titles and "flávio" in titles)


def test_cluster_same_entity_different_fact_stays_apart():
    now = time.time()
    arts = [
        {"title": "Papa Leão XIV vota pelo correio nas eleições dos EUA",
         "ts": now, "source_id": "a", "section": "mundo"},
        {"title": "Papa Leão XIV pede esforços de paz entre Rússia e Ucrânia",
         "ts": now, "source_id": "b", "section": "mundo"},
        {"title": "Papa Leão XIV alerta que IA nunca poderá substituir o ser humano",
         "ts": now, "source_id": "c", "section": "mundo"},
    ]
    assert len(cluster(arts)) == 3


def test_cluster_still_merges_same_fact_with_entity():
    now = time.time()
    arts = [
        {"title": "Bulgária elege presidente pró-Rússia em eleição apertada",
         "ts": now, "source_id": "a", "section": "mundo"},
        {"title": "Bulgária: presidente pró-Rússia vence eleição apertada",
         "ts": now, "source_id": "b", "section": "mundo"},
        {"title": "Bulgária elege presidente pró-Rússia em pleito apertado",
         "ts": now, "source_id": "c", "section": "mundo"},
    ]
    groups = cluster(arts)
    assert len(groups) == 1, [sorted(g) for g in groups]


def test_attach_hubs_ignores_lateral_mention():
    """Menção de passagem no título não faz a história entrar na pauta."""
    from app import attach_hubs
    def st(sid, title, arts):
        return _story(sid, title, arts)
    stories = [
        st("s1", "Flávio Bolsonaro fala pela 1ª vez dos EUA",
           [("G1", "Flávio Bolsonaro fala pela 1ª vez dos EUA", 0, "C"),
            ("UOL", "Flávio Bolsonaro cita eleições antes de 2030", 0, "C")]),
        st("s2", "Trump e a fuga de Flávio Bolsonaro",
           [("G1", "Trump e a fuga de Flávio Bolsonaro", 0, "C"),
            ("UOL", "Trump diz que Flávio pode ficar nos EUA", 0, "C")]),
        st("s3", "Como aliados reagem ao golpismo de Flávio Bolsonaro",
           [("G1", "Como aliados reagem ao golpismo de Flávio Bolsonaro", 0, "C"),
            ("UOL", "Aliados de Flávio Bolsonaro reagem à fuga", 0, "C")]),
        # história sobre outra coisa: Flávio aparece só numa citação lateral
        st("s4", "Democratas cobram que Trump reconheça vitória de Lula",
           [("G1", "Democratas cobram que Trump reconheça vitória de Lula", 0, "C"),
            ("UOL", "Democratas criticam negacionismo de Trump", 0, "C"),
            ("Folha", "Deputados democratas exigem nota de Trump", 0, "C")]),
        st("s5", "Michelle defende Tarcísio e critica aliados de Flávio",
           [("G1", "Michelle chama Jair Bolsonaro de líder", 0, "C"),
            ("UOL", "Michelle defende Tarcísio e rebate aliados", 0, "C")]),
    ]
    out = attach_hubs(stories)
    by = {s["id"]: s.get("hub") for s in out}
    assert by["s1"]["key"] == "flávio bolsonaro"
    assert by["s2"]["key"] == "flávio bolsonaro"
    assert by["s3"]["key"] == "flávio bolsonaro"
    assert by["s4"] is None, "citação solta de Flávio não é pauta"
    assert by["s5"] is None, "só sobrenome (Bolsonaro) não ancora a pauta Flávio"


def test_attach_hubs_ignores_place_names():
    """Estado/cidade não é pauta: 'Mato Grosso' juntava soja, TCE e violência."""
    from app import attach_hubs
    def st(sid, t):
        return _story(sid, t, [("G1", t, 0, "C"), ("UOL", t, 0, "C")])
    stories = [
        st("s1", "Ministros vão a Mato Grosso do Sul verificar denúncias de violência"),
        st("s2", "Esmagamento de soja em Mato Grosso bate recorde histórico em 2026"),
        st("s3", "Presidente do TCE de Mato Grosso sacou R$ 15 milhões em dinheiro"),
        st("s4", "São José dos Campos terá novas linhas de ônibus elétricos"),
        st("s5", "São José dos Campos amplia horário do Anel Viário no sábado"),
    ]
    out = attach_hubs(stories)
    assert all(s.get("hub") is None for s in out), [s.get("hub") for s in out]


def test_cluster_audit_opt_in_does_not_change_groups(tmp_path):
    import json
    now = time.time()
    arts = [
        {"title": "Bulgária elege presidente pró-Rússia em eleição apertada",
         "ts": now, "source_id": "a", "section": "mundo"},
        {"title": "Bulgária: presidente pró-Rússia vence eleição apertada",
         "ts": now, "source_id": "b", "section": "mundo"},
        {"title": "Papa Leão XIV pede paz na Ucrânia",
         "ts": now, "source_id": "c", "section": "mundo"},
    ]
    plain = cluster(arts)
    audit = tmp_path / "pairs.jsonl"
    with_audit = cluster(arts, audit_path=str(audit))
    assert [sorted(g) for g in with_audit] == [sorted(g) for g in plain]
    recs = [json.loads(l) for l in audit.read_text(encoding="utf-8").splitlines()]
    assert recs, "auditoria deve registrar os pares candidatos"
    assert all(set(r) >= {"a", "b", "cos", "shared", "decision", "rule"}
               for r in recs)
    assert {r["decision"] for r in recs} <= {"fused", "rejected"}


def test_framing_terms_distinguishes_sides():
    cov = [
        {"title": "Fuga de Flávio expõe crise do governo", "bucket": "L"},
        {"title": "Fuga de Flávio aprofunda crise do governo", "bucket": "L"},
        {"title": "Viagem de Flávio aos EUA preserva família", "bucket": "R"},
        {"title": "Viagem de Flávio garante segurança da família", "bucket": "R"},
    ]
    f = app.framing_terms(cov)
    assert "fuga" in f["L"] and "viagem" in f["R"]
    assert app.framing_terms(cov[:2]) == {}, "lado único não tem enquadramento"


def test_build_includes_framing():
    arts = [
        {"title": "Fuga de Flávio expõe crise do governo", "link": "https://x/l1",
         "source_id": "l", "source_name": "L", "base_bias": -0.6, "ts": 1.0,
         "published": "2026-11-01T10:00:00+00:00", "section": "politica", "summary": ""},
        {"title": "Fuga de Flávio aprofunda crise do governo", "link": "https://x/l2",
         "source_id": "l2", "source_name": "L2", "base_bias": -0.6, "ts": 1.0,
         "published": "2026-11-01T10:00:00+00:00", "section": "politica", "summary": ""},
        {"title": "Viagem de Flávio aos EUA preserva família", "link": "https://x/r1",
         "source_id": "r", "source_name": "R", "base_bias": 0.6, "ts": 1.0,
         "published": "2026-11-01T10:00:00+00:00", "section": "politica", "summary": ""},
        {"title": "Viagem de Flávio garante segurança da família", "link": "https://x/r2",
         "source_id": "r2", "source_name": "R2", "base_bias": 0.6, "ts": 1.0,
         "published": "2026-11-01T10:00:00+00:00", "section": "politica", "summary": ""},
    ]
    srcs = [{"id": "l", "name": "L", "bias": -0.6, "ownership": "x"},
            {"id": "l2", "name": "L2", "bias": -0.6, "ownership": "x"},
            {"id": "r", "name": "R", "bias": 0.6, "ownership": "y"},
            {"id": "r2", "name": "R2", "bias": 0.6, "ownership": "y"}]
    out = app.build(srcs, arts, {})
    assert out and "framing" in out[0]


def test_entity_alias_translate_chains_stable():
    """F-15: sem colisão entre ALIAS e TRANSLATE; cadeias idempotentes."""
    cases = {"eua": "us", "usa": "us", "brasil": "brazil",
             "ucrânia": "ukraine", "rússia": "russia", "onu": "un",
             "estados unidos": "united states", "reino unido": "uk"}
    def chain(w):
        # mesma ordem de entities(): ALIAS primeiro, depois TRANSLATE
        return app.ENTITY_TRANSLATE.get(app.ENTITY_ALIAS.get(w, w),
                                        app.ENTITY_ALIAS.get(w, w))
    for src, want in cases.items():
        got = chain(src)
        assert got == want, (src, got)
        assert chain(got) == want, f"não idempotente: {src}"


def test_site_url_respects_env(monkeypatch):
    import importlib
    monkeypatch.setenv("BALANCO_SITE_URL", "https://exemplo.test/balanco/")
    import app as appmod
    importlib.reload(appmod)
    assert appmod.SITE_URL == "https://exemplo.test/balanco"
    monkeypatch.delenv("BALANCO_SITE_URL")
    importlib.reload(appmod)
    assert appmod.SITE_URL == "https://hcarta.github.io/balanco"


def test_aosf_link_matcher_is_conservative():
    """Fase 0: não ligar checagem ao tema errado; cai na busca do site."""
    from factcheck import _best_aosf_link
    urls = [
        "https://www.aosfatos.org/noticias/falso-governo-lula-imposto-sobre-heranca-40-porcento/",
        "https://www.aosfatos.org/noticias/video-antigo-circula-nas-redes-para-sugerir-que-flavio-foi-para-os-eua/",
    ]
    ok = _best_aosf_link("Vídeo antigo circula nas redes para sugerir que Flávio foi para os EUA", urls)
    assert ok and "video-antigo" in ok
    assert _best_aosf_link("É falso que Lula recuou sobre fim da escala 6x1", urls) is None


def test_summary_conflict_rejects_macro_topic_bridge():
    """Caso safra Trump × Papa: deks de assuntos distintos barram o elo."""
    import time
    now = time.time()
    a = {"title": "Crítico de Trump, Leão 14 vota pelo correio nas eleições de meio de mandato dos EUA",
         "summary": "Em iniciativa histórica, o papa Leão 14 votou pelo correio nas eleições dos Estados Unidos",
         "ts": now, "source_id": "folha", "section": "mundo"}
    b = {"title": "Trump promete US$ 15 bilhões para agricultores dos EUA de olho em eleições de meio de mandato",
         "summary": "Governo prepara pacote bilionário para o setor, grupo eleitoral dos republicanos",
         "ts": now, "source_id": "estadao", "section": "mundo"}
    shared = set(app.tok(a["title"])) & set(app.tok(b["title"]))
    assert app._summary_conflict(a, b, shared) is True
    toks = [set(app.tok(a["title"])), set(app.tok(b["title"]))]
    X = app.tfidf_matrix([{"title": a["title"]}, {"title": b["title"]}])
    ok, rule = app._pair_decision([a, b], toks, X @ X.T, None, 0, 1, 0.30, 48)
    assert ok is False and rule == "summary_conflict"


def test_summary_conflict_spares_same_event_with_shared_number():
    """Mesmo fato com número em comum não é vetado pelo dek divergente."""
    import time
    now = time.time()
    a = {"title": "Binance sofre ataque hacker de US$ 6,3 bilhões",
         "summary": "Corretora perdeu 6,3 bilhões em criptomoedas após invasão",
         "ts": now, "source_id": "bbc", "section": "economia"}
    b = {"title": "US$ 6,3 bilhões: o maior roubo de criptomoedas da história",
         "summary": "Hackers desviaram 6,3 bilhões de uma corretora",
         "ts": now, "source_id": "band", "section": "economia"}
    shared = set(app.tok(a["title"])) & set(app.tok(b["title"]))
    assert app._summary_conflict(a, b, shared) is False


def test_weak_link_does_not_bridge_two_anchored_clusters():
    """Cluster de tópico: elo fraco não liga dois grupos já ancorados."""
    import time
    now = time.time()
    # cluster A (papa): 3 títulos fortes entre si
    arts = [
        {"title": "Papa Leão XIV vota pelo correio nas eleições dos EUA",
         "ts": now, "source_id": "a", "section": "mundo"},
        {"title": "Papa Leão XIV vota pelo correio nas eleições de meio de mandato",
         "ts": now, "source_id": "b", "section": "mundo"},
        {"title": "Leão XIV vota pelo correio em eleições dos EUA",
         "ts": now, "source_id": "c", "section": "mundo"},
        # cluster B (subsídios): 3 títulos fortes entre si
        {"title": "Trump promete US$ 15 bilhões para agricultores dos EUA",
         "ts": now, "source_id": "d", "section": "economia"},
        {"title": "Trump promete US$ 15 bi a agricultores às vésperas da eleição",
         "ts": now, "source_id": "e", "section": "economia"},
        {"title": "Trump anuncia US$ 15 bilhões para agricultores dos EUA",
         "ts": now, "source_id": "f", "section": "economia"},
        # ponte fraca entre os dois temas
        {"title": "Crítico de Trump, Leão 14 vota pelo correio nas eleições de meio de mandato",
         "ts": now, "source_id": "g", "section": "mundo"},
    ]
    groups = app.cluster(arts)
    gi = next(i for i, a in enumerate(arts) if a["title"].startswith("Papa Leão XIV vota"))
    gj = next(i for i, a in enumerate(arts) if a["title"].startswith("Trump promete"))
    gk = next(i for i, a in enumerate(arts) if a["title"].startswith("Crítico de Trump"))
    def gid(idx):
        for g in groups:
            if idx in g: return frozenset(g)
    assert gid(gi) != gid(gj), "papa e subsídios não podem ficar no mesmo grupo"
    assert gk in gid(gi), "a ponte pertence ao cluster do papa"


def test_weak_link_still_merges_small_story():
    """História de 2 fontes (sem vizinhos fortes) continua fundindo."""
    import time
    now = time.time()
    arts = [
        {"title": "Flávio Bolsonaro admite disputar nova eleição presidencial",
         "ts": now, "source_id": "a", "section": "politica"},
        {"title": "Flávio Bolsonaro cita disputar eleição presidencial antes de 2030",
         "ts": now, "source_id": "b", "section": "politica"},
    ]
    assert len(app.cluster(arts)) == 1


def test_build_includes_recent_windows():
    import time
    from datetime import datetime, timezone
    now = time.time()
    iso = datetime.fromtimestamp(now - 3600, tz=timezone.utc).isoformat()
    title = "Senado aprova marco fiscal em votação apertada"
    srcs = [
        {"id": "a", "name": "A", "bias": -0.5, "factuality": "high",
         "ownership": "x"},
        {"id": "b", "name": "B", "bias": 0.0, "factuality": "high",
         "ownership": "y"},
    ]
    arts = [{
        "title": title, "link": f"https://x/{s['id']}", "source_id": s["id"],
        "source_name": s["name"], "base_bias": s["bias"], "ts": now,
        "published": iso, "section": "politica",
        "summary": "", "first_seen": iso,
    } for s in srcs]
    out = app.build(srcs, arts, {})
    r = out[0]["recent"]
    assert "n_6h" in r and "n_24h" in r
    assert r["n_6h"] >= 1


def test_excluded_title_football():
    for t in ["Flamengo vence o Palmeiras no Brasileirão",
              "Seleção brasileira convoca para a Copa do Mundo",
              "Real Madrid anuncia contratação de Mbappé",
              "Neymar marca em goleada do Santos FC"]:
        assert app.excluded_title(t), t
    # não pode pegar estado/cidade/nome
    for t in ["Governador da Bahia anuncia obra",
              "Fortaleza terá novo hospital",
              "Cruzeiro do Sul amplia aeroporto"]:
        assert not app.excluded_title(t), t


def test_service_headline_finados():
    titles = [
        "Finados em Manaus: veja horários de ônibus e o que abre e fecha",
        "Dia de Finados: veja o que abre e fecha em BH nesta segunda-feira",
        "Museu Oscar Niemeyer abre no feriado de Finados em Curitiba",
    ]
    got = app._service_headline(titles)
    assert got and got.startswith("Funcionamento e horários no feriado de Finados")
    # clima/transporte não deve receber a manchete de funcionamento
    assert app._service_headline([
        "Como fica o tempo no feriado de Finados?",
        "Finados: aeroportos devem receber 2 milhões no feriado",
    ]) is None


def test_attach_front_pages_matches_and_scores():
    stories = [
        {"id": "a", "title": "Flávio Bolsonaro vai a culto evangélico com mulher e Eduardo",
         "articles": [{"title": "Flávio Bolsonaro vai a culto evangélico com mulher e Eduardo",
                       "source": "G1"},
                      {"title": "Flávio Bolsonaro vai a culto evangélico com mulher e Eduardo",
                       "source": "Folha de S.Paulo"}],
         "counts": {"total": 4}, "recent": {"n_6h": 1}},
        {"id": "b", "title": "Binance sofre ataque hacker de US$ 6,3 bilhões",
         "articles": [{"title": "Binance sofre ataque hacker de US$ 6,3 bilhões",
                       "source": "G1"},
                      {"title": "Binance sofre ataque hacker de US$ 6,3 bilhões",
                       "source": "UOL"}],
         "counts": {"total": 10}, "recent": {"n_6h": 0}},
    ]
    desks = {"O Globo": [
        {"title": "Flávio Bolsonaro vai a culto evangélico com mulher e Eduardo",
         "link": "https://x/1"},
        {"title": "Pauta que não está no feed de notícias", "link": "https://x/2"}]}
    out, _, _ = app.attach_front_pages(stories, desks=desks)
    assert out[0]["front"] and out[0]["front"][0]["source"] == "O Globo"
    assert out[1]["front"] == []
    assert out[0]["destaque"] > out[1]["destaque"]


def test_front_dependencies_declared():
    """Regressão: sem bs4/lxml o CI extraía 0 capas e o ranking caía em cobertura."""
    from pathlib import Path
    reqs = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(
        encoding="utf-8").lower()
    assert "beautifulsoup4" in reqs
    assert "lxml" in reqs


def test_front_items_parses_fixture_without_network():
    html = """
    <html><body>
      <a class="manchete" href="/politica/eleicao-eua-musk">
        Eleição nos EUA: Musk testa o que meio bilhão de dólares pode fazer
      </a>
      <a class="manchete" href="/politica/curta">Curta</a>
      <a class="manchete" href="https://exemplo.com/">Home</a>
    </body></html>
    """
    cfg = {"url": "https://exemplo.com/", "sel": "a.manchete", "kind": "anchor"}
    items = app._front_items(html, cfg)
    assert len(items) == 1
    assert items[0]["link"] == "https://exemplo.com/politica/eleicao-eua-musk"


def test_attach_front_pages_reports_stats_per_source():
    stories = [{"id": "a", "title": "Eleição nos EUA: Musk testa o que pode fazer",
                "articles": [{"title": "Eleição nos EUA: Musk testa o que pode fazer",
                              "source": "G1"},
                             {"title": "Eleição nos EUA: Musk testa o que pode fazer",
                              "source": "Folha de S.Paulo"}],
                "counts": {"total": 2}, "recent": {"n_6h": 1}}]
    desks = {"G1": [{"title": "Eleição nos EUA: Musk testa o que pode fazer",
                     "link": "https://x/1"}],
             "UOL": []}
    stats = {}
    out, _, _ = app.attach_front_pages(stories, desks=desks, stats=stats)
    assert stats["G1"] == 1 and stats["UOL"] == 0
    assert stats["unmatched"] == []
    assert out[0]["front_score"] == 1.0


def _mk_front_story(sid, title, n_articles, source="G1", total=None):
    return {"id": sid, "title": title,
            "articles": [{"title": title, "source": source}
                         for _ in range(n_articles)],
            "counts": {"total": total or n_articles},
            "recent": {"n_6h": 1}}


def test_front_pauta_lists_all_feed_stories_of_the_theme():
    stories = [
        _mk_front_story("a", "Irã propõe reabrir Estreito de Ormuz em dois dias", 3),
        _mk_front_story("b", "Líder do Irã ordena resposta sem restrições a ataque", 2),
        _mk_front_story("c", "Binance sofre ataque hacker de US$ 6,3 bilhões", 4),
    ]
    desks = {"UOL": [{"title": "Irã propõe reabrir Hormuz em dois dias",
                      "link": "https://x/1"}]}
    out, front_only, pautas = app.attach_front_pages(stories, desks=desks)
    p = next(x for x in pautas if x["label"] == "Irã / Hormuz")
    assert set(p["story_ids"]) == {"a", "b"}
    assert p["n_stories"] == 2
    assert p["coverage_total"] == 5
    assert p["lead"]["source"] == "UOL"
    irã = {s["id"]: s for s in out}
    assert irã["a"]["pauta"] == "Irã / Hormuz"
    assert irã["b"]["pauta_n_stories"] == 2
    assert "pauta" not in irã["c"]  # Binance não entra na pauta do Irã
    assert front_only == []


def test_front_pauta_without_feed_story_becomes_front_only():
    stories = [_mk_front_story("a", "Binance sofre ataque hacker de US$ 6,3 bilhões", 3)]
    desks = {"Folha de S.Paulo": [
        {"title": "Freezers de supermercados são atacados na Europa",
         "link": "https://x/1"}]}
    _, front_only, pautas = app.attach_front_pages(stories, desks=desks)
    p = next(x for x in pautas if x["label"] == "Ataque hacker / freezers")
    assert p["story_ids"] == []
    assert p["pseudo_id"].startswith("fp-")
    assert front_only and front_only[0]["front_only"] is True


def test_front_pauta_requires_the_defining_dimension():
    """Conceito largo ("Trump") não pode arrastar história de outro assunto."""
    stories = [
        _mk_front_story(
            "a", "Eleição nos EUA: Musk testa o que meio bilhão pode fazer", 3),
        _mk_front_story(
            "b", "Trump ameaça ataque ao Irã e eleva tensão no Oriente Médio", 3),
    ]
    desks = {"G1": [{"title": "Eleição legislativa nos EUA pode tirar força de Trump",
                     "link": "https://x/1"}]}
    out, _, pautas = app.attach_front_pages(stories, desks=desks)
    p = next(x for x in pautas if x["label"] == "Eleição EUA / Trump")
    assert "a" in p["story_ids"]
    assert "b" not in p["story_ids"]
    assert "pauta" not in {s["id"]: s for s in out}["b"]


def _art(title, group, bias):
    return {"title": title, "group": group, "bias": bias,
            "bucket": app.bucket(bias), "piece_kind": "hard_news"}


def test_front_pauta_aggregates_bias_by_editorial_group():
    """P3: barra da pauta deduplica grupo e soma as histórias do tema."""
    stories = [
        {"id": "a", "title": "Irã propõe reabrir Estreito de Ormuz em dois dias",
         "articles": [_art("Irã propõe reabrir Estreito de Ormuz em dois dias", "g1", -0.5),
                      _art("Irã propõe reabrir Hormuz em dois dias", "folha", 0.1)],
         "counts": {"total": 2}, "recent": {"n_6h": 1}},
        {"id": "b", "title": "Líder do Irã ordena resposta sem restrições",
         "articles": [_art("Líder do Irã ordena resposta sem restrições", "folha", 0.1),
                      _art("Líder do Irã ordena resposta sem restrições", "cnn", 0.9)],
         "counts": {"total": 2}, "recent": {"n_6h": 1}},
    ]
    desks = {"UOL": [{"title": "Irã propõe reabrir Hormuz em dois dias",
                      "link": "https://x/1"}]}
    _, _, pautas = app.attach_front_pages(stories, desks=desks)
    p = next(x for x in pautas if x["label"] == "Irã / Hormuz")
    assert p["n_groups"] == 3          # g1, folha, cnn (folha não duplica)
    assert p["n_articles"] == 4
    assert p["counts"]["CL"] == 1 and p["counts"]["C"] == 1
    assert p["counts"]["R"] == 1
    assert p["pct"] == {"L": 0, "CL": 33, "C": 33, "CR": 0, "R": 33}
    assert p["blindspot"] is None
    assert p["avg_bias"] == round((-0.5 + 0.1 + 0.9) / 3, 2)


def test_front_pauta_becomes_hub_label_with_entity_fallback():
    """P4: conceito rotula "Outros ângulos"; hub de entidade é fallback."""
    stories = [
        {"id": "a", "title": "Irã propõe reabrir Estreito de Ormuz em dois dias",
         "articles": [_art("Irã propõe reabrir Ormuz em dois dias", "g1", 0.0),
                      _art("Irã propõe reabrir Ormuz", "folha", 0.0)],
         "counts": {"total": 2}, "recent": {"n_6h": 1},
         "hub": {"key": "irã", "label": "Irã", "size": 4}},
        {"id": "b", "title": "Líder do Irã ordena resposta sem restrições",
         "articles": [_art("Líder do Irã ordena resposta", "cnn", 0.0),
                      _art("Líder do Irã adverte", "uol", 0.0)],
         "counts": {"total": 2}, "recent": {"n_6h": 1}, "hub": None},
        {"id": "c", "title": "Binance sofre ataque hacker de US$ 6,3 bilhões",
         "articles": [_art("Binance sofre ataque hacker", "g1", 0.0)],
         "counts": {"total": 1}, "recent": {"n_6h": 0},
         "hub": {"key": "binance", "label": "Binance", "size": 3}},
    ]
    desks = {"UOL": [{"title": "Irã propõe reabrir Hormuz em dois dias",
                      "link": "https://x/1"}]}
    out, _, _ = app.attach_front_pages(stories, desks=desks)
    by = {s["id"]: s for s in out}
    assert by["a"]["hub"] == {"key": "pauta:irã-hormuz",
                              "label": "Irã / Hormuz", "size": 2,
                              "concept": True}
    assert by["b"]["hub"]["label"] == "Irã / Hormuz"
    assert by["c"]["hub"]["label"] == "Binance"   # fora da pauta: fallback


def test_single_story_pauta_keeps_entity_hub():
    story = {"id": "d",
             "title": "Freezers de supermercados são alvo de hackers na Europa",
             "articles": [_art("Freezers de supermercados são alvo de hackers", "g1", 0.0),
                          _art("Freezers de supermercados são atacados", "folha", 0.0)],
             "counts": {"total": 2}, "recent": {"n_6h": 1},
             "hub": {"key": "freezers", "label": "Freezers", "size": 2}}
    desks = {"G1": [{"title": "Freezers de supermercados são alvo de hackers",
                     "link": "https://x/1"}]}
    out, _, _ = app.attach_front_pages([story], desks=desks)
    assert out[0]["hub"] == {"key": "freezers", "label": "Freezers", "size": 2}


def test_front_items_extracts_standfirst():
    html = ('<a href="/pol/x"><h1>Fuga de Flávio Bolsonaro aos EUA leva '
            'militares a abraçarem Tarcísio</h1>'
            '<p class="c-main-headline__standfirst">Integrantes das Forças '
            'Armadas criticam abandono de tropa por senador</p></a>')
    cfg = {"url": "https://exemplo.com/", "sel": "h1", "kind": "heading"}
    items = app._front_items(html, cfg)
    assert items[0]["summary"].startswith("Integrantes das Forças Armadas")


def test_front_pauta_call_uses_latest_story_headline():
    """A chamada é a manchete mais recente, mesmo fora do topo da capa."""
    def st(sid, title, link, upd):
        return {"id": sid, "title": title,
                "articles": [_art(title, "g1", 0.0),
                             {**_art(title, "folha", 0.0), "link": link}],
                "counts": {"total": 2}, "recent": {"n_6h": 1},
                "updated": upd}
    stories = [
        st("a", "Irã propõe reabrir Estreito de Ormuz em dois dias",
           "https://x/old", "2026-11-02T10:00:00+00:00"),
        st("b", "Líder do Irã ordena resposta sem restrições a ataque",
           "https://x/new", "2026-11-02T12:00:00+00:00"),
    ]
    desks = {"UOL": [{"title": "Irã propõe reabrir Hormuz em dois dias",
                      "link": "https://x/old", "summary": "antiga"}],
             "G1": [{"title": "Líder do Irã ordena resposta sem restrições",
                     "link": "https://x/new", "summary": "nova"}]}
    _, _, pautas = app.attach_front_pages(stories, desks=desks)
    p = next(x for x in pautas if x["label"] == "Irã / Hormuz")
    assert p["call"]["source"] == "G1"      # mais recente, apesar de #2 na capa
    assert p["call"]["summary"] == "nova"


def test_destaque_saturates_front_signal_at_three_journals():
    """Regra 2: 3 jornais vencem 2 jornais com cluster maior."""
    a = {"id": "a", "title": "Eleição nos EUA: Musk testa o que meio bilhão pode fazer",
         "articles": [_art("Eleição nos EUA: Musk testa o que meio bilhão pode fazer",
                           "g1", 0.0)] * 3,
         "counts": {"total": 15}, "recent": {"n_6h": 1},
         "updated": "2026-11-02T12:00:00+00:00"}
    b = {"id": "b", "title": "Flávio Bolsonaro utilizou comboio de carros e jatos",
         "articles": [_art("Flávio Bolsonaro utilizou comboio de carros e jatos",
                           "folha", 0.0)] * 2,
         "counts": {"total": 35}, "recent": {"n_6h": 0},
         "updated": "2026-11-02T12:00:00+00:00"}
    title_a = "Eleição nos EUA: Musk testa o que meio bilhão pode fazer"
    title_b = "Flávio Bolsonaro utilizou comboio de carros e jatos"
    desks = {src: [{"title": title_a, "link": f"https://a/{i}"}]
             for i, src in enumerate(["O Globo", "G1", "CNN Brasil"])}
    desks.update({src: [{"title": title_b, "link": f"https://b/{i}"}]
                  for i, src in enumerate(["Folha de S.Paulo", "UOL"])})
    out, _, _ = app.attach_front_pages([a, b], desks=desks)
    by = {s["id"]: s for s in out}
    assert by["a"]["front_score"] == 3.0 and by["b"]["front_score"] == 2.0
    assert by["a"]["destaque"] > by["b"]["destaque"]


def test_front_saturation_counts_journals_even_at_position_4():
    """3º jornal em #4 ainda conta como 3º jornal (regra 2)."""
    a = {"id": "a", "title": "Eleição nos EUA: Musk testa o que meio bilhão pode fazer",
         "articles": [_art("Eleição nos EUA: Musk testa o que meio bilhão pode fazer",
                           "g1", 0.0)] * 3,
         "counts": {"total": 16}, "recent": {"n_6h": 4},
         "updated": "2026-11-02T12:00:00+00:00"}
    b = {"id": "b", "title": "Flávio Bolsonaro utilizou comboio de carros e jatos",
         "articles": [_art("Flávio Bolsonaro utilizou comboio de carros e jatos",
                           "folha", 0.0)] * 2,
         "counts": {"total": 41}, "recent": {"n_6h": 4},
         "updated": "2026-11-02T12:00:00+00:00"}
    ta = "Eleição nos EUA: Musk testa o que meio bilhão pode fazer"
    tb = "Flávio Bolsonaro utilizou comboio de carros e jatos"
    fill = "Cidade inaugura nova praça no bairro central"
    desks = {
        "O Globo": [{"title": ta, "link": "https://a/1"}],
        "CNN Brasil": [{"title": ta, "link": "https://a/2"}],
        "G1": [{"title": fill, "link": "https://f/1"},
               {"title": fill + " dois", "link": "https://f/2"},
               {"title": fill + " três", "link": "https://f/3"},
               {"title": ta, "link": "https://a/3"}],
        "Folha de S.Paulo": [{"title": tb, "link": "https://b/1"}],
        "UOL": [{"title": tb, "link": "https://b/2"}],
    }
    out, _, _ = app.attach_front_pages([a, b], desks=desks)
    by = {s["id"]: s for s in out}
    assert by["a"]["front_n_sources"] == 3
    assert by["a"]["front_score"] == 2.7      # #1 + #1 + #4
    assert by["a"]["destaque"] > by["b"]["destaque"]


def test_three_journals_always_outrank_two_regardless_of_coverage():
    """Regra 2 calibrada: 3 jornais > 2 jornais, mesmo com 1 cobertura."""
    a = {"id": "a", "title": "Eleição nos EUA: Musk testa o que meio bilhão pode fazer",
         "articles": [_art("Eleição nos EUA: Musk testa o que meio bilhão pode fazer",
                           "g1", 0.0)] * 3,
         "counts": {"total": 2}, "recent": {"n_6h": 0},
         "updated": "2026-11-02T12:00:00+00:00"}
    b = {"id": "b", "title": "Flávio Bolsonaro utilizou comboio de carros e jatos",
         "articles": [_art("Flávio Bolsonaro utilizou comboio de carros e jatos",
                           "folha", 0.0)] * 2,
         "counts": {"total": 40}, "recent": {"n_6h": 0},
         "updated": "2026-11-02T12:00:00+00:00"}
    ta = "Eleição nos EUA: Musk testa o que meio bilhão pode fazer"
    tb = "Flávio Bolsonaro utilizou comboio de carros e jatos"
    desks = {src: [{"title": ta, "link": f"https://a/{i}"}]
             for i, src in enumerate(["O Globo", "G1", "CNN Brasil"])}
    desks.update({src: [{"title": tb, "link": f"https://b/{i}"}]
                  for i, src in enumerate(["Folha de S.Paulo", "UOL"])})
    out, _, _ = app.attach_front_pages([a, b], desks=desks)
    by = {s["id"]: s for s in out}
    assert by["a"]["destaque"] > by["b"]["destaque"]


def test_front_pauta_lead_follows_call_story():
    """A barra/cobertura do slot devem ser da história exibida na chamada."""
    def st(sid, title, link, upd, total):
        return {"id": sid, "title": title,
                "articles": [_art(title, "g1", 0.0),
                             {**_art(title, "folha", 0.0), "link": link}],
                "counts": {"total": total}, "recent": {"n_6h": 1},
                "updated": upd}
    a = st("a", "Irã propõe reabrir Estreito de Ormuz em dois dias",
           "https://x/old", "2026-11-02T10:00:00+00:00", 40)
    b = st("b", "Líder do Irã ordena resposta sem restrições a ataque",
           "https://x/new", "2026-11-02T12:00:00+00:00", 3)
    desks = {"UOL": [{"title": "Irã propõe reabrir Hormuz em dois dias",
                      "link": "https://x/old"}],
             "G1": [{"title": "Líder do Irã ordena resposta sem restrições",
                     "link": "https://x/new"}]}
    out, _, pautas = app.attach_front_pages([a, b], desks=desks)
    by = {s["id"]: s for s in out}
    p = next(x for x in pautas if x["label"] == "Irã / Hormuz")
    assert p["call"]["source"] == "G1"        # mais recente
    assert p["story_id"] == "b"               # lead = história da chamada
    assert by["b"]["front_n_sources"] == 2
    assert by["b"]["front"]
    assert not by["a"].get("front")


def test_front_unmatched_reports_headlines_without_concept():
    stories = [_mk_front_story("a", "Binance sofre ataque hacker de US$ 6,3 bilhões", 2)]
    desks = {"Folha de S.Paulo": [
        {"title": "Prefeitura inaugura um centro de reciclagem na zona sul",
         "link": "https://x/9"}]}
    stats = {}
    app.attach_front_pages(stories, desks=desks, stats=stats)
    assert stats["unmatched"] and stats["unmatched"][0]["source"] == "Folha de S.Paulo"
    assert "reciclagem" in stats["unmatched"][0]["title"]


def test_emergent_pauta_from_two_front_pages():
    """Fase 2: tema fora do lexicon, aberto em 2 capas no topo, vira pauta."""
    stories = [_mk_front_story(
        "a", "Enchente atinge o Vale do Itajaí e deixa famílias desabrigadas", 2)]
    desks = {
        "G1": [{"title": "Enchente atinge o Vale do Itajaí e deixa famílias desabrigadas",
                "link": "https://x/1"}],
        "UOL": [{"title": "Chuva forte alaga o Vale do Itajaí e deixa desabrigados",
                 "link": "https://x/2"}],
    }
    out, _, pautas = app.attach_front_pages(stories, desks=desks)
    em = [p for p in pautas if p.get("emergent")]
    assert len(em) == 1
    assert em[0]["n_sources"] == 2
    assert "a" in em[0]["story_ids"]
    assert out[0]["pauta"] == em[0]["label"]
    assert out[0]["front_n_sources"] == 2


def test_emergent_pauta_low_page_without_feed_is_ignored():
    """Página baixa e sem cobertura no feed não vira pauta (é ruído)."""
    stories = [_mk_front_story("b", "Binance sofre ataque hacker de US$ 6 bi", 2)]
    airbnb = "Reservas de Airbnb em Paris despencam após onda de tumultos"
    fillers = ["Prefeitura anuncia obras na zona norte", "Time local vence campeonato regional",
               "Feira de artesanato ocupa a praça central"]
    desks = {
        "G1": [{"title": t, "link": f"https://f/{i}"} for i, t in enumerate(fillers)]
              + [{"title": airbnb, "link": "https://x/5"}],
        "UOL": [{"title": t + " dois", "link": f"https://g/{i}"}
                for i, t in enumerate(fillers)]
               + [{"title": airbnb, "link": "https://x/6"}],
    }
    _, _, pautas = app.attach_front_pages(stories, desks=desks)
    assert not any("Airbnb" in p["label"] for p in pautas if p.get("emergent"))


def _em_desks():
    return {
        "G1": [{"title": "Enchente atinge o Vale do Itajaí e deixa famílias desabrigadas",
                "link": "https://x/1"}],
        "UOL": [{"title": "Chuva forte alaga o Vale do Itajaí e deixa desabrigados",
                 "link": "https://x/2"}],
    }


def test_pauta_override_applies_key_label_and_alias(monkeypatch):
    monkeypatch.setattr(app, "PAUTAS_OVERRIDES", [{
        "key": "vale-itajai", "label": "Enchente no Vale do Itajaí",
        "match": ["vale do itajai"], "aliases": ["enchente-sc"]}])
    stories = [_mk_front_story(
        "a", "Enchente atinge o Vale do Itajaí e deixa famílias desabrigadas", 2)]
    stats = {}
    _, _, pautas = app.attach_front_pages(stories, desks=_em_desks(), stats=stats)
    em = [p for p in pautas if p.get("emergent")][0]
    assert em["key"] == "vale-itajai"
    assert em["label"] == "Enchente no Vale do Itajaí"
    assert stats["aliases"]["enchente-sc"] == "vale-itajai"


def test_emergent_key_reuses_previous_snapshot():
    stories = [_mk_front_story(
        "a", "Enchente atinge o Vale do Itajaí e deixa famílias desabrigadas", 2)]
    prev = [{"key": "enchente-2026", "label": "Enchente SC",
             "links": ["https://x/1", "https://x/2"]}]
    stats = {}
    _, _, pautas = app.attach_front_pages(
        stories, desks=_em_desks(), previous_pautas=prev, stats=stats)
    em = [p for p in pautas if p.get("emergent")][0]
    assert em["key"] == "enchente-2026"
    assert em["label"] == "Enchente SC"
    assert stats["reused"] == 1


def test_emergent_pauta_uses_embeddings_when_lexical_fails(monkeypatch):
    stories = [_mk_front_story(
        "a", "Temporal deixa moradores sem casa no interior de Santa Catarina", 2)]

    def fake_embed(docs, model_name=""):
        import numpy as np
        out = []
        for d in docs:
            t = d["title"].lower()
            v = [1.0, 0.0] if ("temporal" in t or "santa catarina" in t
                               or "enchente" in t or "alaga" in t) else [0.0, 1.0]
            out.append(v)
        X = np.array(out, dtype=float)
        X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
        return X

    monkeypatch.setattr(app, "embed_matrix", fake_embed)
    _, _, sem = app.attach_front_pages(stories, desks=_em_desks())
    # léxico sozinho não liga a história (a pauta pode existir como front_only)
    assert not any("a" in p["story_ids"] for p in sem if p.get("emergent"))
    out, _, com = app.attach_front_pages(stories, desks=_em_desks(), use_embed=True)
    em = [p for p in com if p.get("emergent")]
    assert em and "a" in em[0]["story_ids"]


def test_recent_groups_prefers_published_over_first_seen():
    """Matéria antiga recolhida agora não pode contar como 'recente'."""
    from datetime import datetime, timezone
    now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc).timestamp()
    arts = [
        {"published": "2026-10-31T12:00:00+00:00",
         "first_seen": "2026-11-03T11:00:00+00:00", "group": "g1"},
        {"published": "2026-10-31T13:00:00+00:00",
         "first_seen": "2026-11-03T11:00:00+00:00", "group": "g2"},
    ]
    assert app._recent_groups(arts, 6, now=now) == 0
    arts[1]["published"] = "2026-11-03T11:30:00+00:00"
    assert app._recent_groups(arts, 6, now=now) == 1


def test_recompute_sets_first_published():
    s = {"articles": [
        {"published": "2026-10-31T17:00:00+00:00",
         "first_seen": "2026-11-03T11:00:00+00:00", "group": "g1",
         "piece_kind": "hard_news", "bias": 0.0, "bucket": "C",
         "title": "a", "source": "X"},
        {"published": "2026-11-02T10:00:00+00:00",
         "first_seen": "2026-11-03T11:00:00+00:00", "group": "g2",
         "piece_kind": "hard_news", "bias": 0.0, "bucket": "C",
         "title": "b", "source": "Y"},
    ], "counts": {}, "updated": "2026-11-02T10:00:00+00:00"}
    out = app._recompute(s)
    assert out["first_published"] == "2026-10-31T17:00:00+00:00"


def test_front_items_fallback_when_selector_breaks():
    html = ('<a href="/x"><h2>Manchete nova com mais de vinte e cinco '
            'caracteres para o teste</h2></a>')
    cfg = {"url": "https://exemplo.com/", "sel": ".sumiu", "kind": "heading"}
    items = app._front_items(html, cfg)
    assert items and items[0]["title"].startswith("Manchete nova")


def test_emergent_front_only_requires_three_journals():
    """2 capas sem história no feed não bastam para virar pauta."""
    stories = [_mk_front_story("b", "Binance sofre ataque hacker de US$ 6 bi", 2)]
    nova = "Universidade federal anuncia novo campus no interior"
    desks = {
        "G1": [{"title": nova, "link": "https://x/1"}],
        "UOL": [{"title": nova + " do estado", "link": "https://x/2"}],
    }
    _, _, pautas = app.attach_front_pages(stories, desks=desks)
    assert not [p for p in pautas if p.get("emergent")]
