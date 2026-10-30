#!/usr/bin/env python3
"""Balanço MVP — coleta RSS/sitemaps, agrupa stories, gera docs/data.json.

Viés é FIXO por fonte (posicionamento da publicação), sem análise por matéria.
O LLM é opt-in (--llm) e só deve ser usado quando explicitamente desejado.
"""
import argparse
import json
import math
import os
import re
from collections import Counter
from datetime import datetime, timezone

import numpy as np
import yaml

BASE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(BASE, "docs")

STOP = set("""a ao aos aquela aquelas aquele aqueles aquilo as até com como da das de do dos
e ela elas ele eles em entre era eram essa essas esse esses esta estas este estes eu foi foram
haja hajam há isso isto já lhe lhes mais mas me mesmo meu meus minha minhas muito na nas não nos
nossa nossas nosso nossos num numa o os ou para pela pelas pelo pelos por qual quando que quem
se seja sejam sem ser seu seus sua suas só são também tem têm ter terá terão uma umas uns vai vão
dos das foi ser ter vez dia dias ano anos contra entre após sobre sob depois antes onde qual quais
seu sua seu pode podem deve devem muito mais menos entre para nas nos pelos pelas deste desta
disso desse dessa naquele naquela tudo todos toda todas outro outra outros outros outras cada vez
tri trimestre bi bilhão bilhões milhão milhões lucro prejuízo alta queda recuo registra registro
fake checagem checado""".split())

TOKEN_RE = re.compile(r"[a-zà-ú0-9]+", re.I)


def tok(text: str) -> list[str]:
    out = []
    for w in TOKEN_RE.findall(text.lower()):
        if len(w) >= 3 and w not in STOP:
            out.append(w)
    return out


def load_sources(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["sources"]


def fetch_all(sources, per_feed=30, store=None, window_h=72, run_ts=""):
    from collectors import collect_one
    from store import PER_SOURCE_CAP

    articles = []
    n_ok, n_err, n_new = 0, 0, 0
    for s in sources:
        try:
            fresh, hs = collect_one(s, limit=per_feed if store is None else 2000,
                                    store=store)
            n_got_new = 0
            if store is not None:
                n_got_new = store.upsert_articles(s["id"], fresh)
                n_new += n_got_new
                got = store.recent(s["id"], window_h=window_h,
                                   limit=max(per_feed, PER_SOURCE_CAP))
                status = hs.get("status", "ok")
                if hs.get("status") == "error" and got:
                    status = "stale"  # usa cache porque a rede falhou
                store.log_fetch(s["id"], run_ts, len(fresh), len(got),
                                status, hs.get("ms", 0),
                                "; ".join(hs.get("errors", [])))
            else:
                got = fresh[:per_feed]
            for a in got:
                a.update({
                    "source_id": s["id"],
                    "source_name": s["name"],
                    "base_bias": float(s.get("bias", 0)),
                })
            articles.extend(got)
            kind = s.get("fetcher", "rss")
            new = f" (+{n_got_new} novos)" if store is not None else ""
            print(f"  {s['name']:22} {len(got):3} artigos{new}  ({kind})")
            n_ok += 1
        except Exception as ex:
            if store is not None:
                store.log_fetch(s["id"], run_ts, 0, 0, "error", 0, str(ex)[:200])
            print(f"  {s['name']:22} ERRO: {ex}")
            n_err += 1
    # dedup por link
    seen, uniq = set(), []
    for a in articles:
        if a["link"] and a["link"] not in seen:
            seen.add(a["link"])
            uniq.append(a)
    return uniq, {"n_ok": n_ok, "n_err": n_err, "n_new": n_new}


def tfidf_matrix(docs):
    # Só título: resumos têm boilerplate e causam falsos positivos
    toks = [tok(d["title"]) for d in docs]
    df = Counter()
    for t in toks:
        for w in set(t):
            df[w] += 1
    vocab = {w: i for i, w in enumerate(df) if df[w] >= 2 or len(df) < 500}
    # garante palavras do título mesmo que raras
    for t in toks:
        for w in set(t):
            if w not in vocab and len(vocab) < 4000:
                vocab[w] = len(vocab)
    n, v = len(docs), len(vocab)
    X = np.zeros((n, v), dtype=np.float32)
    for i, t in enumerate(toks):
        c = Counter(t)
        for w, f in c.items():
            j = vocab.get(w)
            if j is not None:
                X[i, j] = (1 + math.log(f)) * (math.log(n / max(1, df.get(w, 1))) + 1)
    norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    return X / norms


def cluster(articles, thresh=0.38, window_h=48):
    n = len(articles)
    if n == 0:
        return []
    X = tfidf_matrix(articles)
    S = X @ X.T
    # tokens por doc p/ exigir sobreposição real (evita agrupar "Lula X" com "Lula Y")
    toksets = [set(tok(a["title"])) for a in articles]
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
            if S[i, j] >= thresh and len(toksets[i] & toksets[j]) >= 2:
                dt = abs(articles[i]["ts"] - articles[j]["ts"]) / 3600
                if dt <= window_h:
                    union(i, j)
    groups: dict[int, list] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    # ordena grupos por tamanho e recência
    out = sorted(groups.values(), key=lambda g: (-len(g), -max(articles[i]["ts"] for i in g)))
    return out


def bucket(score):
    if score <= -0.5:
        return "L"
    if score >= 0.5:
        return "R"
    return "C"


def build(sources, articles, llm_scores, thresh=0.38):
    groups = cluster(articles, thresh=thresh)
    meta = {s["id"]: s for s in sources}
    stories = []
    for gid, g in enumerate(groups):
        # uma "história" precisa de pelo menos 2 veículos distintos
        if len({articles[i]["source_id"] for i in g}) < 2:
            continue
        items = []
        for i in g:
            a = articles[i]
            llm = (llm_scores or {}).get(a["link"])
            if llm:  # apenas quando o usuário roda com --llm
                score, via = llm["score"], "llm"
            else:
                # posicionamento FIXO da publicação, sem análise por matéria
                score, via = round(float(a["base_bias"]), 2), "fonte"
            items.append({**a, "bias_score": round(score, 2), "via": via,
                          "bucket": bucket(score)})
        items.sort(key=lambda x: x["bias_score"])
        l = sum(1 for x in items if x["bucket"] == "L")
        c = sum(1 for x in items if x["bucket"] == "C")
        r = sum(1 for x in items if x["bucket"] == "R")
        tot = len(items)
        avg = sum(x["bias_score"] for x in items) / tot
        blind = None
        if tot >= 4:
            left_out = l / tot <= 0.15
            right_out = r / tot <= 0.15
            if left_out and right_out:
                blind = "both"  # só o centro cobre: os dois lados estão cegos
            elif left_out:
                blind = "left"
            elif right_out:
                blind = "right"
        rep = max(items, key=lambda x: len(x["title"]))
        # resumo: pega o primeiro disponível (sitemaps não trazem dek)
        summary = next((x["summary"] for x in items if x.get("summary")), "")
        stories.append({
            "id": f"s{gid:03d}", "title": rep["title"],
            "summary": summary[:300],
            "section": rep.get("section", ""),
            "avg_bias": round(avg, 2),
            "counts": {"L": l, "C": c, "R": r, "total": tot},
            "pct": {"L": round(100 * l / tot), "C": round(100 * c / tot), "R": round(100 * r / tot)},
            "blindspot": blind,
            "updated": max(x["published"] for x in items),
            "articles": [{
                "source": x["source_name"], "source_id": x["source_id"],
                "title": x["title"], "link": x["link"],
                "bias": x["bias_score"], "bucket": x["bucket"], "via": x["via"],
                "section": x.get("section", ""),
                "factuality": meta.get(x["source_id"], {}).get("factuality"),
                "ownership": meta.get(x["source_id"], {}).get("ownership"),
            } for x in items],
        })
    stories.sort(key=lambda s: (-s["counts"]["total"], s["updated"]), reverse=False)
    stories.sort(key=lambda s: s["counts"]["total"], reverse=True)
    return stories


def _check_payload(c, score):
    return {
        "verdict": c["verdict"],
        "label": c["label"],
        "title": c["title"],
        "link": c["link"],
        "checker": c["checker"],
        "published": c["published"],
        "score": round(score, 2),
    }


def attach_checks(stories, checks, story_min=0.34, article_min=0.45):
    """Casa histórias/matérias com checagens por sobreposição ponderada (IDF).

    Exige termo raro em comum + força mínima, para separar "mesma alegação" de
    "mesmo assunto". Não afirma que a matéria é falsa: apenas liga a checagem.
    """
    for s in stories:
        s["checks"] = []
    if not checks:
        return stories, {}, []

    s_sets = [set(tok(s["title"])) for s in stories]
    a_ref, a_sets = [], []
    for si, s in enumerate(stories):
        for ai, a in enumerate(s["articles"]):
            a_ref.append((si, ai))
            a_sets.append(set(tok(a["title"])))
    c_sets = [set(tok(c["title"])) for c in checks]

    allsets = s_sets + a_sets + c_sets
    n = len(allsets)
    df = Counter()
    for ts in allsets:
        for w in ts:
            df[w] += 1
    idf = {w: math.log(n / max(1, c)) + 1 for w, c in df.items()}

    def match(a, b, floor):
        inter = a & b
        if len(inter) < 2:
            return 0.0
        den = min(sum(idf.get(t, 1) for t in a), sum(idf.get(t, 1) for t in b)) or 1
        cov = sum(idf.get(t, 1) for t in inter) / den
        rare = any(df[t] <= 4 for t in inter)      # termo específico da alegação
        strong = len(inter) >= 4 or cov >= 0.5
        return round(cov, 2) if (cov >= floor and rare and strong) else 0.0

    # nível história
    for si, s in enumerate(stories):
        cands = []
        for ci, c in enumerate(checks):
            sc = match(s_sets[si], c_sets[ci], story_min)
            if sc:
                cands.append((sc, ci))
        cands.sort(reverse=True)
        s["checks"] = [_check_payload(checks[ci], sc) for sc, ci in cands[:2]]

    # nível matéria + histórico por fonte
    ledger = {}
    matches = []
    for k, (si, ai) in enumerate(a_ref):
        cands = [(match(a_sets[k], c_sets[ci], article_min), ci) for ci in range(len(checks))]
        cands = [(sc, ci) for sc, ci in cands if sc]
        if not cands:
            continue
        cands.sort(reverse=True)
        sc, ci = cands[0]
        art = stories[si]["articles"][ai]
        art["check"] = _check_payload(checks[ci], sc)
        L = ledger.setdefault(art["source_id"], {"total": 0, "falso": 0,
                                                 "enganoso": 0, "verdadeiro": 0, "checagem": 0})
        L["total"] += 1
        v = art["check"]["verdict"]
        L[v] = L.get(v, 0) + 1
        matches.append({
            "source_id": art["source_id"], "source": art["source"],
            "article": art["title"], "article_link": art["link"],
            "check": checks[ci]["title"], "check_link": checks[ci]["link"],
            "checker": checks[ci]["checker"], "verdict": v,
            "score": sc, "date": checks[ci]["published"],
        })

    for L in ledger.values():
        L["revisar"] = L.get("falso", 0) >= 2  # sinal p/ revisão humana, não rótulo automático

    return stories, ledger, matches


LEDGER_PATH = os.path.join(BASE, "state", "factcheck_ledger.json")


def merge_factcheck_ledger(matches):
    """Acumula evidências entre execuções (dedup por matéria+checagem)."""
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    data = {"sources": {}, "matches": []}
    if os.path.exists(LEDGER_PATH):
        try:
            with open(LEDGER_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data.setdefault("sources", {})
    data.setdefault("matches", [])
    seen = {(m.get("article_link"), m.get("check_link")) for m in data["matches"]}
    for m in matches:
        key = (m["article_link"], m["check_link"])
        if key in seen:
            continue
        seen.add(key)
        data["matches"].append(m)
        s = data["sources"].setdefault(m["source_id"], {
            "total": 0, "falso": 0, "enganoso": 0, "verdadeiro": 0, "checagem": 0})
        s["total"] += 1
        s[m["verdict"]] = s.get(m["verdict"], 0) + 1
    for s in data["sources"].values():
        s["revisar"] = s.get("falso", 0) >= 2
    with open(LEDGER_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data["sources"]


def main():
    ap = argparse.ArgumentParser(
        description="Balanço — viés FIXO por fonte (sem análise por matéria por padrão).")
    ap.add_argument("--llm", action="store_true",
                    help="classifica viés por artigo via LLM (opcional; consome tokens)")
    ap.add_argument("--no-llm", action="store_true", help=argparse.SUPPRESS)  # compat
    ap.add_argument("--per-feed", type=int, default=25)
    ap.add_argument("--thresh", type=float, default=0.38)
    ap.add_argument("--no-checks", action="store_true",
                    help="não coleta checagens do G1 Fato ou Fake / Lupa")
    ap.add_argument("--fresh", action="store_true",
                    help="ignora o cache (baixa tudo de novo, sem HTTP condicional)")
    ap.add_argument("--window", type=float, default=72,
                    help="janela de artigos em horas (padrão 72)")
    ap.add_argument("--db", default=None, help="caminho do cache SQLite")
    args = ap.parse_args()

    import time as _time
    t0 = _time.monotonic()
    run_ts = datetime.now(timezone.utc).isoformat()

    store = None
    if not args.fresh:
        from store import Store
        store = Store(args.db) if args.db else Store()
        print(f"[0/4] cache: {store.db.execute('SELECT COUNT(*) FROM articles').fetchone()[0]} artigos guardados")

    print("== Balanço MVP ==")
    sources = load_sources(os.path.join(BASE, "sources.yaml"))
    print(f"[1/4] coletando {len(sources)} feeds...")
    articles, fsum = fetch_all(sources, per_feed=args.per_feed, store=store,
                               window_h=args.window, run_ts=run_ts)
    print(f"  total: {len(articles)} artigos únicos ({fsum['n_new']} novos no banco)")

    llm_scores = {}
    if args.llm and not args.no_llm:
        if os.getenv("OPENAI_API_KEY"):
            from classify_llm import classify_batch
            print("[2/4] viés por artigo via LLM (--llm ativado)...")
            llm_scores = classify_batch(articles)
        else:
            print("[2/4] --llm pedido, mas OPENAI_API_KEY ausente → viés fixo por fonte")
    else:
        print("[2/4] viés fixo por fonte (sem análise por matéria)")

    print("[3/4] agrupando stories...")
    stories = build(sources, articles, llm_scores, thresh=args.thresh)

    checks = []
    if not args.no_checks:
        try:
            from factcheck import fetch_all as fetch_checks
            checks = fetch_checks()
            print(f"[3b/4] {len(checks)} checagens (G1 Fato ou Fake + Lupa)")
        except Exception as ex:
            print(f"[3b/4] checagens indisponíveis: {ex}")

    stories, ledger, matches = attach_checks(stories, checks)
    leverage = merge_factcheck_ledger(matches) if checks else {}
    if checks:
        print(f"[3c/4] {len(matches)} matéria(s) casaram com checagens nesta rodada")

    os.makedirs(SITE, exist_ok=True)
    health = store.health() if store is not None else {}
    sources_out = [{**s, "factcheck": leverage.get(s["id"]) or ledger.get(s["id"]),
                    "health": health.get(s["id"])}
                   for s in sources]
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(),
               "n_articles": len(articles), "n_stories": len(stories),
               "n_factchecks": len(checks), "n_matches": len(matches),
               "n_new": fsum["n_new"],
               "sources": sources_out,
               "factchecks": checks[:80],
               "stories": stories}
    with open(os.path.join(SITE, "data.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    with open(os.path.join(BASE, "state", "health.json"), "w", encoding="utf-8") as f:
        json.dump({"run_ts": run_ts, "sources": health}, f, ensure_ascii=False, indent=1)
    print(f"[4/4] {len(stories)} stories → docs/data.json")

    if store is not None:
        ms = int((_time.monotonic() - t0) * 1000)
        store.log_run(run_ts, fsum["n_ok"], fsum["n_err"],
                      fsum["n_new"], len(articles), ms)
        store.close()
        print(f"  rodada em {ms/1000:.1f}s (cache em state/cache.db)")
        for a in store_alerts(health):
            print(f"  ⚠ {a}")
    # soltas (sem par) p/ debug
    print("Top stories:")
    for s in stories[:8]:
        print(f"  [{s['counts']['total']:2}x L{s['pct']['L']:2}% C{s['pct']['C']:2}% R{s['pct']['R']:2}%] {s['title'][:80]}")


def store_alerts(health: dict) -> list[str]:
    msgs = []
    for sid, h in (health or {}).items():
        if not h:
            continue
        if h.get("err_streak", 0) >= 2:
            msgs.append(f"{sid}: ERRO {h['err_streak']} rodadas seguidas")
        elif h.get("empty"):
            msgs.append(f"{sid}: 0 artigos na última rodada")
    return msgs


if __name__ == "__main__":
    main()
