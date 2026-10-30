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


_EMB_MODEL = None
_EMB_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


def embed_matrix(docs, model_name: str = _EMB_NAME):
    """Embeddings semânticos (MiniLM multilíngue) normalizados. Falha se lib/modelo ausente."""
    global _EMB_MODEL
    from sentence_transformers import SentenceTransformer
    if _EMB_MODEL is None or getattr(_EMB_MODEL, "_bname", None) != model_name:
        _EMB_MODEL = SentenceTransformer(model_name)
        _EMB_MODEL._bname = model_name
    X = _EMB_MODEL.encode([d["title"] for d in docs], convert_to_numpy=True,
                          show_progress_bar=False)
    norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    return X / norms


def tfidf_matrix(docs):
    # Só título: resumos têm boilerplate e causam falsos positivos
    toks = [tok(d["title"]) for d in docs]
    df = Counter()
    for t in toks:
        for w in set(t):
            df[w] += 1
    kept = [w for w in df if df[w] >= 2 or len(df) < 500]
    vocab = {w: i for i, w in enumerate(kept)}
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


def pair_decision(t1: str, t2: str, thresh: float = 0.38,
                  background: list[str] = ()) -> tuple[bool, float, int]:
    """Decisão par-a-par espelhando cluster(): cosseno TF-IDF + 2+ tokens em comum.

    O TF-IDF é calculado sobre background + os dois títulos (como na produção,
    onde o IDF vem do corpus da rodada). Retorna (agrupa, cosseno, shared).
    """
    docs = [{"title": t} for t in list(background) + [t1, t2]]
    X = tfidf_matrix(docs)
    cos = float(X[-2] @ X[-1])
    shared = len(set(tok(t1)) & set(tok(t2)))
    return (cos >= thresh and shared >= 2), round(cos, 3), shared


def eval_pairs(pairs: list[tuple], thresh: float = 0.38):
    """Precisão/revocação do agrupamento sobre pares (titulo_a, titulo_b, rotulo[, src_a, src_b]).

    Uma única matriz TF-IDF sobre todos os títulos — igual à produção — e a
    mesma regra de pares do cluster(), incluindo a exigência extra para pares
    da mesma fonte (Fase 2.3; sem o bônus de seção, indisponível no fixture).
    Retorna (precisao, revocacao, (tp, fp, fn, tn)).
    """
    titles = [t for p in pairs for t in (p[0], p[1])]
    X = tfidf_matrix([{"title": t} for t in titles])
    tp = fp = fn = tn = 0
    for k, p in enumerate(pairs):
        a, b, label = p[0], p[1], p[2]
        a_src = p[3] if len(p) > 3 else None
        b_src = p[4] if len(p) > 4 else None
        cos = float(X[2 * k] @ X[2 * k + 1])
        shared = len(set(tok(a)) & set(tok(b)))
        pred = cos >= thresh and shared >= 2
        if pred and a_src is not None and a_src == b_src:
            ta, tb = tok(a), tok(b)
            if len(ta) >= 2 and len(tb) >= 2 and ta[:2] == tb[:2]:
                pred = False  # série da casa
            elif cos < thresh + 0.10 or shared < 3:
                pred = False
        if pred and label == 1:
            tp += 1
        elif pred:
            fp += 1
        elif label == 1:
            fn += 1
        else:
            tn += 1
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    return prec, rec, (tp, fp, fn, tn)


def cluster(articles, thresh=0.38, window_h=48, use_embed=False):
    n = len(articles)
    if n == 0:
        return []
    X = tfidf_matrix(articles)
    S = X @ X.T
    Se = None
    if use_embed:
        try:
            Xe = embed_matrix(articles)
            Se = Xe @ Xe.T
        except Exception as e:
            print(f"  [aviso] embeddings indisponíveis ({e}); usando TF-IDF")
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
            shared = toksets[i] & toksets[j]
            if len(shared) < 1:
                continue
            pred = S[i, j] >= thresh and len(shared) >= 2
            if Se is not None and not pred and Se[i, j] >= 0.70 and len(shared) >= 1:
                pred = True  # híbrido: paráfrase semântica (Fase 2.2)
            if not pred:
                continue
            si, sj = articles[i].get("source_id"), articles[j].get("source_id")
            if si is not None and si == sj:
                # mesma fonte: exige mais evidência (Fase 2.3)
                ti, tj = tok(articles[i]["title"]), tok(articles[j]["title"])
                if len(ti) >= 2 and len(tj) >= 2 and ti[:2] == tj[:2]:
                    continue  # série da casa ("Pinguins X", "VÍDEOS: Jornal ...")
                same_sec = bool(articles[i].get("section")) and \
                    articles[i].get("section") == articles[j].get("section")
                floor = thresh + (0.12 if same_sec else 0.10)
                if S[i, j] < floor or len(shared) < 3:
                    continue
            dt = abs(articles[i]["ts"] - articles[j]["ts"]) / 3600
            w = pair_window(articles[i].get("section"), articles[j].get("section"),
                              window_h)
            if dt <= w:
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


def _norm_sec(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()


# opinião/análise duram dias; hard news dura horas (Fase 2.5)
LONGFORM_SECTIONS = {"vozes", "coluna", "colunas", "colunistas", "opiniao",
                     "blog", "blogs", "artigo", "artigos", "editorial"}
SHORT_SECTIONS = {"politica", "economia", "mundo", "internacional", "eleicoes",
                  "poder", "brasil", "financas", "mercados", "esportes",
                  "seguranca", "educacao", "saude"}


def pair_window(sec_a, sec_b, default: float = 48) -> float:
    """Janela em horas para o par: vale a mais duradoura (opinião alcança o fato)."""
    a, b = _norm_sec(sec_a), _norm_sec(sec_b)
    if a in LONGFORM_SECTIONS or b in LONGFORM_SECTIONS:
        return 168.0
    if a in SHORT_SECTIONS or b in SHORT_SECTIONS:
        return 24.0
    return float(default)


# Rótulos de editoria para filtro e kicker (Fase 3.3)
SECTION_LABELS = {
    "politica": "Política", "poder": "Poder", "eleicoes": "Eleições",
    "economia": "Economia", "financas": "Economia", "mercados": "Mercado",
    "dinheiro": "Economia", "negocios": "Negócios",
    "mundo": "Mundo", "internacional": "Mundo",
    "brasil": "Brasil", "sp": "São Paulo", "rio": "Rio",
    "esportes": "Esportes", "futebol": "Esportes",
    "cultura": "Cultura", "entretenimento": "Cultura", "celebridades": "Cultura",
    "tecnologia": "Tecnologia", "ciencia": "Ciência", "saude": "Saúde",
    "educacao": "Educação", "seguranca": "Segurança",
    "opiniao": "Opinião", "vozes": "Opinião", "coluna": "Opinião",
    "colunas": "Opinião", "colunistas": "Opinião", "editorial": "Opinião",
    "artigo": "Opinião", "artigos": "Opinião", "blogs": "Opinião",
    "tec": "Tecnologia", "tecmundo": "Tecnologia",
    "sao-paulo": "São Paulo", "televisao": "TV", "receitas": "Receitas",
    "empresas": "Negócios", "imprensa": "Mídia", "jornalismo": "Mídia",
    "poder-internacional": "Poder", "poder-governo": "Poder", "poder-gente": "Poder",
    "cartalab": "Dados",
}


def section_label(raw: str | None) -> str:
    key = _norm_sec(raw)
    if key in SECTION_LABELS:
        return SECTION_LABELS[key]
    if key and len(key) <= 24:
        return key[:1].upper() + key[1:]
    return "Geral"


def rep_score(item: dict, meta: dict) -> float:
    """Pontua o melhor título representante da história (Fase 2.4).

    Prefere informativo e neutro: tamanho saudável, fonte de factualidade alta,
    sem clickbait (?, !, CAIXA ALTA) nem excesso de aspas.
    """
    t = item.get("title", "")
    s = min(len(t), 140) / 140
    f = (meta.get(item.get("source_id"), {}) or {}).get("factuality")
    if f in ("very_high", "high"):
        s += 0.30
    elif f in ("low", "very_low"):
        s -= 0.30
    if "?" in t:
        s -= 0.40
    if "!" in t:
        s -= 0.40
    if sum(1 for w in t.split() if w.isupper() and len(w) > 2):
        s -= 0.20
    if t.count('"') >= 4 or t.count("“") + t.count("”") >= 2:
        s -= 0.10
    return round(s, 3)


def build(sources, articles, llm_scores, thresh=0.38, use_embed=False):
    groups = cluster(articles, thresh=thresh, use_embed=use_embed)
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
        rep = max(items, key=lambda x: rep_score(x, meta))
        # resumo: pega o primeiro disponível (sitemaps não trazem dek)
        summary = next((x["summary"] for x in items if x.get("summary")), "")
        stories.append({
            "id": f"s{gid:03d}", "title": rep["title"],
            "summary": summary[:300],
            "section": rep.get("section", ""),
            "section_label": section_label(rep.get("section")),
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
                "section_label": section_label(x.get("section")),
                "image": x.get("image", ""),
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


def build_idf(token_sets: list[set]) -> tuple[dict, Counter]:
    """DF + IDF sobre um corpus de conjuntos de tokens."""
    n = len(token_sets)
    df: Counter = Counter()
    for ts in token_sets:
        for w in ts:
            df[w] += 1
    idf = {w: math.log(n / max(1, c)) + 1 for w, c in df.items()}
    return idf, df


def claim_overlap(a: set, b: set, idf: dict, df: Counter, floor: float = 0.34) -> float:
    """Sobreposição ponderada por raridade: separa "mesma alegação" de "mesmo assunto".

    Exige (1) 2+ tokens em comum, (2) ao menos um termo raro (específico da
    alegação) e (3) força mínima (4+ tokens ou cobertura >= 0.5).
    Retorna a cobertura (0–1) ou 0.0.
    """
    inter = a & b
    if len(inter) < 2:
        return 0.0
    den = min(sum(idf.get(t, 1) for t in a), sum(idf.get(t, 1) for t in b)) or 1
    cov = sum(idf.get(t, 1) for t in inter) / den
    rare = any(df[t] <= 4 for t in inter)
    strong = len(inter) >= 4 or cov >= 0.5
    return round(cov, 2) if (cov >= floor and rare and strong) else 0.0


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
    idf, df = build_idf(allsets)

    def match(a, b, floor):
        return claim_overlap(a, b, idf, df, floor)

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
    ap.add_argument("--embed", action="store_true",
                    help="usa embeddings semânticos como complemento (híbrido; baixa modelo ~470MB na 1ª vez)")
    ap.add_argument("--no-checks", action="store_true",
                    help="não coleta checagens do G1 Fato ou Fake / Lupa")
    ap.add_argument("--body", action="store_true",
                    help="enriquece matérias (meta + corpo público, com cache; ignora robots de editoria)")
    ap.add_argument("--body-cap", type=int, default=40,
                    help="máximo de páginas buscadas por rodada com --body")
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

    if args.body:
        from enrich import enrich_articles
        estats = enrich_articles(articles, store, cap=args.body_cap)
        print(f"[1b/4] enriquecimento: {estats['filled']} resumos preenchidos, "
              f"{estats['bodies']} corpos no cache, {estats['paywalled']} com muro")

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
    stories = build(sources, articles, llm_scores, thresh=args.thresh,
                    use_embed=args.embed)

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
