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
               [("G1", "Binance sofre ataque hacker de US$ 6,3 bilhões", 0.5, "R"),
                ("UOL", "Binance sofre ataque hacker de US$ 6,3 bilhões: Coreia do Norte é suspeita", 0.5, "R")])
    b = _story("s2", "Ataque à Binance: hackers norte-coreanos de criptomoedas estão entre os suspeitos",
               [("CNN", "Ataque à Binance: hackers norte-coreanos de criptomoedas estão entre os suspeitos", 0.5, "R"),
                ("Folha", "Hackers da Coreia do Norte roubam US$ 6,3 bilhões da Binance", 0.5, "R")])
    out = consolidate([a, b])
    assert len(out) == 1
    s = out[0]
    assert s["counts"]["L"] == 0
    assert s["counts"]["C"] == 0
    assert s["counts"]["R"] == 4
    assert s["counts"]["total"] == 4
    assert s["counts"]["independent"] == 4
    assert s["counts"]["groups"] == {"L": 0, "C": 0, "R": 4}
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
    assert out[0]["counts"]["groups"] == {"L": 1, "C": 2, "R": 0}
    assert out[0]["blindspot"] == "right"


def test_independent_counts_collapses_same_owner():
    arts = [
        {"source_id": "g1", "group": "globo", "bias": 0.0, "bucket": "C"},
        {"source_id": "oglobo", "group": "globo", "bias": 0.1, "bucket": "C"},
        {"source_id": "folha", "group": "folha", "bias": -0.6, "bucket": "L"},
        {"source_id": "uol", "group": "uol", "bias": 0.0, "bucket": "C"},
    ]
    gc, ind, avg = app.independent_counts(arts, "bias")
    assert gc == {"L": 1, "C": 2, "R": 0}
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
    assert out[0]["counts"]["groups"] == {"L": 1, "C": 1, "R": 0}
    assert out[0]["pct"] == {"L": 50, "C": 50, "R": 0}

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
    assert s["counts"]["groups"] == {"L": 1, "C": 2, "R": 0}
    assert s["counts"]["independent"] == 3
    assert s["blindspot"] == "right"
    assert s["pct"] == {"L": 33, "C": 67, "R": 0}
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
