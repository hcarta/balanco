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
    n_ok, n_err, n_new, n_dropped = 0, 0, 0, 0
    for s in sources:
        try:
            fresh, hs = collect_one(s, limit=per_feed if store is None else 2000,
                                    store=store)
            kept = [a for a in fresh
                    if not excluded_section(a.get("section"))
                    and not excluded_title(a.get("title"))]
            n_dropped += len(fresh) - len(kept)
            fresh = kept
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
                    "kind": s.get("kind", "br"),
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
    return uniq, {"n_ok": n_ok, "n_err": n_err, "n_new": n_new, "n_dropped": n_dropped}


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


# Editorias fora da edição (o foco é poder, economia e sociedade)
EXCLUDED_SECTIONS = {"esportes", "futebol", "astrologia", "loterias"}

# Conteúdo de serviço mora em editorias genéricas: filtra pelo título
EXCLUDED_TITLE = re.compile(
    r"lotof[aá]cil|mega-sena|megasena|lotomania|dupla\ssena|timemania"
    r"|\bquina\b[^.]{0,40}(sorteio|resultado|concurso|dezenas)"
    r"|hor[oó]scopo|mapa\s+astral|previs[aã]o\s+do\s+tempo|fases?\s+da\s+lua"
    r"|\bloteria\b.{0,40}(sorteio|resultado|concurso|pr[eê]mio)",
    re.I)


def excluded_section(raw: str | None) -> bool:
    return _norm_sec(raw) in EXCLUDED_SECTIONS


def excluded_title(title: str | None) -> bool:
    return bool(EXCLUDED_TITLE.search(title or ""))


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
                blind = None  # só o centro cobre: sem viés em jogo, não é blindspot
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


def _check_payload(c, score, terms=()):
    return {
        "verdict": c["verdict"],
        "label": c["label"],
        "title": c["title"],
        "link": c["link"],
        "checker": c["checker"],
        "published": c["published"],
        "score": round(score, 2),
        "terms": sorted(terms)[:6],
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


ENTITY_STOP = {"para", "como", "após", "entre", "sobre", "com", "por", "dos", "das",
               "the", "a", "an", "after", "before", "with", "from", "this", "that",
               "says", "said", "over", "amid", "during", "will", "has", "have",
               "more", "what", "when", "while", "about", "into", "says"}

# Genéricos: aparecem em qualquer pauta e não provam tópico em comum
ENTITY_GENERIC = {"brasil", "brazil", "estados", "unidos", "united states", "us",
                  "usa", "eua", "uk", "reino unido", "mundo", "world", "país", "pais",
                  "country", "governo", "government", "presidente", "president",
                  "ministro", "minister", "ministério", "ministry", "federal"}

ENTITY_ALIAS = {"brasil": "brazil", "eua": "us", "usa": "us",
                "estados unidos": "united states", "reino unido": "uk"}


def entities(title: str | None) -> set:
    """Nomes próprios e siglas: âncoras de tópico entre idiomas e estilos.

    Inclui sequências capitalizadas multi-palavra (+ seus pares internos),
    capitalizadas isoladas fora do início e siglas (US, ONU)."""
    t = title or ""
    runs = re.findall(r"[A-ZÀ-Ú][\wà-ú]+(?:\s+[A-ZÀ-Ú][\wà-ú]+)+", t)
    out: set = set()
    for run in runs:
        parts = run.split()
        out.add(run.lower())
        for a, b in zip(parts, parts[1:]):
            out.add(f"{a} {b}".lower())
    toks = re.findall(r"[A-ZÀ-Ú][\wà-ú]*", t)
    for w in toks[1:]:
        if len(w) >= 3:
            out.add(w.lower())
    for w in toks:
        if re.fullmatch(r"[A-Z]{2,3}", w or ""):
            out.add(w.lower())
    if toks and len(toks[0]) >= 4:
        out.add(toks[0].lower())
    norm = {ENTITY_ALIAS.get(w, w) for w in out}
    return {w for w in norm if w not in ENTITY_STOP and len(w) >= 2}


def entity_match(a: set, b: set) -> tuple[bool, list]:
    """Mesmo tópico? 2+ entidades em comum, com ao menos uma multi-palavra
    específica (ou 2+ específicas). Genéricos (países, "governo") não contam
    como evidência sozinhos — foi assim que "BTS" casou com "espionagem chinesa"
    (só compartilhavam "estados/unidos"). Retorna (casa, termos)."""
    inter = a & b
    if len(inter) < 2:
        return False, []
    multi = sorted(x for x in inter if " " in x and x not in ENTITY_GENERIC)
    spec = sorted(x for x in inter if x not in ENTITY_GENERIC)
    if multi or len(spec) >= 2:
        return True, (multi + [x for x in spec if x not in multi])[:6]
    return False, []


# Não-jornalismo no pool longform: programas, quizzes, agendas, podcasts (F3.1)
NON_JOURNALISM = re.compile(
    r"assist[ai] ao programa|programa de \d|palavras cruzadas|\bquiz\b"
    r"|crossword|ao vivo agora|newsletter de|boletim de \d|edi[çc][ãa]o de hoje"
    r"|podcast completa|ouvinte|agenda do dia|hor[óo]scopo", re.I)

# Marcadores de análise (para F3.2: peça da mesma fonte só entra se for análise)
ANALYSIS_MARKERS = re.compile(
    r"an[áa]lise|por que|como \w+ (funciona|mudou|afeta)|entrevista"
    r"|conversa com|bastidores|longform|reportagem especial|perfil"
    r"|o que (isso|isso significa)|o futuro d[oe]|guia", re.I)


def _is_analysis(title: str) -> bool:
    return bool(ANALYSIS_MARKERS.search(title or ""))


def _story_entities(s) -> set:
    """Entidades de todas as manchetes da história (recall maior que só a representante)."""
    out: set = set()
    for a in s.get("articles", []):
        out |= entities(a.get("title", ""))
    return out


def _recompute(s) -> dict:
    """Recalcula contagens, média e blindspot a partir das matérias da história."""
    arts = s.get("articles", [])
    l = sum(1 for x in arts if x.get("bucket") == "L")
    c = sum(1 for x in arts if x.get("bucket") == "C")
    r = sum(1 for x in arts if x.get("bucket") == "R")
    tot = len(arts) or 1
    blind = None
    if tot >= 4:
        left_out = l / tot <= 0.15
        right_out = r / tot <= 0.15
        if left_out and right_out:
            blind = None  # só o centro cobre: não é blindspot
        elif left_out:
            blind = "left"
        elif right_out:
            blind = "right"
    s["counts"] = {"L": l, "C": c, "R": r, "total": len(arts)}
    s["pct"] = {"L": round(100 * l / tot), "C": round(100 * c / tot), "R": round(100 * r / tot)}
    s["avg_bias"] = round(sum(x.get("bias", 0) for x in arts) / tot, 2)
    s["blindspot"] = blind
    return s


def _title_cov(a: set, b: set) -> float:
    """Fração do título mais curto coberta pelo mais longo (0–1).

    Sem peso IDF de propósito: a métrica ponderada variava com o tamanho do
    corpus (0.36 no corpus real, 0.19 num recorte pequeno), o que tornava o
    limiar não transportável entre rodadas e testes.
    """
    if not a or not b:
        return 0.0
    return round(len(a & b) / min(len(a), len(b)), 2)


def consolidate(stories, window_h=48.0, use_embed=False, emb_min=0.70,
                rare_min=2, rare_df=12, cov_min=0.35):
    """F2: funde histórias que descrevem o MESMO fato — não o mesmo assunto.

    Dois sinais independentes, ambos obrigatórios:
      1. entidades específicas em comum (via `entity_match`);
      2. evidência de que é o mesmo fato: >= `cov_min` de cobertura do título
         mais curto com >= `rare_min` tokens raros, OU embedding >= `emb_min`.

    Medido em 31/10/2026 (104 histórias): só entidades fundiria "Rubio e Vieira
    conversam" com "Trump e Milei pressionam" (ambos citam Flávio Bolsonaro).
    Cobertura de título separa: fato igual 0.36–0.40, assunto adjacente
    0.00–0.29 ("Mato Grosso: violência" × "TCE de Mato Grosso"; "Binance" ×
    "Coreia do Sul e Japão"). Por isso a fusão é conservadora por desenho.
    """
    if len(stories) < 2:
        return stories
    titles = [a.get("title", "") for s in stories for a in s.get("articles", [])]
    _, df = build_idf([set(tok(t)) for t in titles])
    ents = [_story_entities(s) for s in stories]
    rtok = [set(tok(s.get("title", ""))) for s in stories]
    ts = [_ts_of(s) for s in stories]

    X = None
    if use_embed:
        try:
            X = embed_matrix([{"title": s.get("title", "")} for s in stories])
        except Exception as e:
            print(f"  [aviso] embeddings indisponíveis na consolidação ({e})")

    n = len(stories)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if abs(ts[i] - ts[j]) / 3600 > window_h:
                continue
            ok, _ = entity_match(ents[i], ents[j])
            if not ok:
                continue
            shared = rtok[i] & rtok[j]
            rare = sum(1 for t in shared if df.get(t, 99) <= rare_df)
            cov = _title_cov(rtok[i], rtok[j])
            emb = float(X[i] @ X[j]) if X is not None else 0.0
            same_fact = (rare >= rare_min and cov >= cov_min) or emb >= emb_min
            if same_fact:
                parent[find(i)] = find(j)

    groups: dict[int, list] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    if len(groups) == n:
        return stories

    merged = []
    for g in groups.values():
        if len(g) == 1:
            merged.append(stories[g[0]])
            continue
        # representante: a história mais coberta (empate: mais recente)
        g_sorted = sorted(g, key=lambda i: (-stories[i]["counts"]["total"], -ts[i]))
        rep = dict(stories[g_sorted[0]])
        absorbed = [stories[i] for i in g_sorted[1:]]
        seen, arts = set(), []
        for i in g_sorted:
            for a in stories[i].get("articles", []):
                if a.get("link") in seen:
                    continue
                seen.add(a.get("link"))
                arts.append(a)
        arts.sort(key=lambda x: x.get("bias", 0))
        rep["articles"] = arts
        rep["summary"] = next((x.get("summary") for x in arts if x.get("summary")),
                              rep.get("summary", ""))[:300]
        rep["updated"] = max(stories[i].get("updated", "") for i in g)
        rep["developments"] = [{"id": s["id"], "title": s["title"],
                                "total": s["counts"]["total"],
                                "blindspot": s.get("blindspot")} for s in absorbed]
        merged.append(_recompute(rep))
    merged.sort(key=lambda s: -s["counts"]["total"])
    return merged


def _ts_of(s) -> float:
    try:
        return datetime.fromisoformat(str(s.get("updated", "")).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


# Pauta = narrativa compartilhada (ex.: "Flávio Bolsonaro"). Não funde histórias:
# agrupa para navegação, preservando a comparação de enquadramento de cada fato.
HUB_STOP = ENTITY_GENERIC | {
    "são paulo", "rio de janeiro", "brasília", "brasilia", "minas gerais",
    "rio grande do sul", "estados unidos", "reino unido", "america latina",
    "américa latina", "oriente médio", "oriente medio", "união europeia",
}
HUB_ACRONYMS = {"stf", "tse", "pf", "pgr", "cnj", "tcu", "bndes", "ibge", "copom",
                "g20", "brics", "onu", "otan", "pt", "pl", "psdb", "ptb", "pcdob"}


def _hub_label(key: str) -> str:
    parts = [w.upper() if w in HUB_ACRONYMS else w[:1].upper() + w[1:]
             for w in key.split()]
    return " ".join(parts)


def attach_hubs(stories, min_stories=3, window_h=72.0):
    """F2: marca cada história com a "pauta" (narrativa) a que pertence.

    Só nomes próprios multi-palavra servem de chave (nunca "lula" ou "senado"):
    genéricos agrupariam pautas sem relação. Não altera contagens — a história
    continua sendo o fato; a pauta é só navegação entre ângulos.
    """
    ents = [_story_entities(s) for s in stories]
    ts = [_ts_of(s) for s in stories]
    index: dict[str, list[int]] = {}
    for i, e in enumerate(ents):
        for k in e:
            if " " in k and k not in HUB_STOP:
                index.setdefault(k, []).append(i)
    for s in stories:
        s["hub"] = None
    cands = {}
    for k, ids in index.items():
        if len(ids) < min_stories:
            continue
        span = (max(ts[i] for i in ids) - min(ts[i] for i in ids)) / 3600
        if span > window_h:
            continue
        cands[k] = ids
    for i, s in enumerate(stories):
        mine = [(len(ids), len(k), k) for k, ids in cands.items() if i in ids]
        if not mine:
            continue
        _, _, k = max(mine)
        s["hub"] = {"key": k, "label": _hub_label(k), "size": len(cands[k])}
    return stories


def attach_longreads(stories, articles, longform_ids, per_story=3):
    """Liga cada história a longform (piauí & cia) pelo mesmo tópico.

    Não afirma nada sobre o artigo: só sugere aprofundamento, com link.
    F3: exclui não-jornalismo, evita redundância com a cobertura da própria
    história (exceto análise) e limita a 1 peça por fonte.
    """
    pool = []
    for a in articles:
        if a.get("source_id") in longform_ids:
            if NON_JOURNALISM.search(a.get("title", "")):
                continue  # F3.1: programa/quiz/agenda não é aprofundamento
            pool.append((entities(a.get("title", "") + " " + (a.get("summary") or "")),
                         a))
    for s in stories:
        s["longreads"] = []
        se = entities(s.get("title", ""))
        if not se:
            continue
        covered = {a.get("source") or a.get("source_name") for a in s.get("articles", [])}
        cands = []
        for le, a in pool:
            ok, terms = entity_match(se, le)
            if ok:
                # F3.2: se a fonte já cobre a história, só peça de análise entra
                if a.get("source_name") in covered and not _is_analysis(a.get("title", "")):
                    continue
                cands.append((len(terms), a["link"], a))
        seen, out, used_src = set(), [], set()
        for _, link, a in sorted(cands, reverse=True):
            if link in seen or a.get("source_name") in used_src:
                continue  # F3.3: no máx. 1 peça por fonte por história
            seen.add(link)
            used_src.add(a.get("source_name"))
            out.append({"source": a.get("source_name", ""), "title": a.get("title", ""),
                        "link": link,
                        "terms": sorted((se & entities(a.get("title", ""))) |
                                        (se & entities(a.get("summary") or "")))[:6]})
            if len(out) >= per_story:
                break
        s["longreads"] = out
    return stories


def diversify_longreads(stories):
    """F3.3: uma mesma peça só é sugerida na história mais coberta do seu tópico.

    Evita que uma peça viral (ex.: a mesma análise do Nexo) apareça em 8
    histórias diferentes do mesmo dia. Não há fallback: se a história perde
    todas as peças, ela fica sem "Aprofunde-se" — repetir a peça de outra
    história seria pior que omitir.
    """
    best = {}
    for s in sorted(stories, key=lambda x: (-x.get("counts", {}).get("total", 0), x.get("updated", ""))):
        for lr in s.get("longreads", []):
            best.setdefault(lr["link"], s["id"])
    for s in stories:
        s["longreads"] = [lr for lr in s.get("longreads", [])
                          if best.get(lr["link"]) == s["id"]]
    return stories


def attach_world(stories, intl_articles, per_story=3):
    """Liga cada história à repercussão internacional (mesmo tópico, outro idioma)."""
    pool = [(entities(a.get("title", "")), a) for a in intl_articles]
    for s in stories:
        s["world"] = []
        se = entities(s.get("title", ""))
        if not se:
            continue
        cands = []
        for ie, a in pool:
            if not ie:
                continue
            ok, terms = entity_match(se, ie)
            if ok:
                cands.append((len(terms), a.get("link", ""), a, terms))
        seen, out = set(), []
        for _, link, a, terms in sorted(cands, reverse=True):
            if not link or link in seen:
                continue
            seen.add(link)
            out.append({"source": a.get("source_name", ""), "title": a.get("title", ""),
                        "link": link, "terms": terms})
            if len(out) >= per_story:
                break
        s["world"] = out
    return stories


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

    def terms(a, b):
        return sorted(a & b)[:6]

    # nível história
    for si, s in enumerate(stories):
        cands = []
        for ci, c in enumerate(checks):
            sc = match(s_sets[si], c_sets[ci], story_min)
            if sc:
                cands.append((sc, ci))
        cands.sort(reverse=True)
        s["checks"] = [_check_payload(checks[ci], sc, terms(s_sets[si], c_sets[ci]))
                       for sc, ci in cands[:2]]

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
        art["check"] = _check_payload(checks[ci], sc, terms(a_sets[k], c_sets[ci]))
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
            "terms": ";".join(sorted(a_sets[k] & c_sets[ci])[:6]),
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
    print(f"  total: {len(articles)} artigos únicos ({fsum['n_new']} novos no banco, {fsum['n_dropped']} fora do recorte)")

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
    news = [a for a in articles if a.get("kind", "br") != "intl"]
    intl = [a for a in articles if a.get("kind") == "intl"]
    print(f"  {len(news)} nacionais + {len(intl)} internacionais (fora das barras)")
    stories = build(sources, news, llm_scores, thresh=args.thresh,
                    use_embed=args.embed)
    n_before = len(stories)
    stories = consolidate(stories, use_embed=args.embed)
    stories = attach_hubs(stories)
    n_hub = len({s["hub"]["key"] for s in stories if s.get("hub")})
    print(f"[3a/4] {n_before} grupos → {len(stories)} histórias consolidadas "
          f"({n_before - len(stories)} fusões de mesmo fato), {n_hub} pautas")

    longform_ids = {s["id"] for s in sources if s.get("longform")}
    stories = attach_longreads(stories, news, longform_ids)
    stories = diversify_longreads(stories)
    stories = attach_world(stories, intl)
    n_lr = sum(1 for s in stories if s.get("longreads"))
    n_w = sum(1 for s in stories if s.get("world"))
    print(f"[3b/4] {n_lr} histórias com aprofundamento, {n_w} com repercussão internacional")

    checks = []
    if not args.no_checks:
        try:
            from factcheck import fetch_all as fetch_checks
            checks = fetch_checks()
            print(f"[3c/4] {len(checks)} checagens (G1 Fato ou Fake + Lupa + Aos Fatos)")
        except Exception as ex:
            print(f"[3b/4] checagens indisponíveis: {ex}")

    stories, ledger, matches = attach_checks(stories, checks)
    leverage = merge_factcheck_ledger(matches) if checks else {}
    if checks:
        print(f"[3d/4] {len(matches)} matéria(s) casaram com checagens nesta rodada")

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
    archive_snapshot(SITE, payload)
    write_feed(SITE, stories)
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


SITE_URL = "https://hcarta.github.io/balanco"
ARCHIVE_KEEP = 90  # edições diárias mantidas


def archive_snapshot(site_dir: str, payload: dict) -> str | None:
    """Guarda uma edição por dia em arquivo/AAAA-MM-DD.json (Fase 6.1)."""
    import glob
    adir = os.path.join(site_dir, "arquivo")
    os.makedirs(adir, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dest = os.path.join(adir, f"{day}.json")
    if not os.path.exists(dest):
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    files = sorted(glob.glob(os.path.join(adir, "????-??-??.json")))
    for old in files[:-ARCHIVE_KEEP]:
        try:
            os.remove(old)
        except OSError:
            pass
    # índice do arquivo
    items = []
    for fp in sorted(glob.glob(os.path.join(adir, "????-??-??.json")), reverse=True):
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
            items.append((os.path.basename(fp)[:10], d.get("n_stories", 0),
                          d.get("generated_at", "")))
        except Exception:
            continue
    lis = "\n".join(
        f'<li><a href="{d}.json">{d}</a> — {n} histórias</li>' for d, n, _ in items)
    html = f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Edições anteriores — Balanço</title>
<style>body{{font-family:Georgia,serif;max-width:640px;margin:40px auto;padding:0 20px;color:#16130f;background:#faf8f4}}a{{color:#1d4ed8}}li{{margin:8px 0}}</style>
</head><body><h1>Edições anteriores</h1><p><a href="../">← Voltar ao Balanço de hoje</a></p><ul>{lis}</ul></body></html>"""
    with open(os.path.join(adir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    return dest


def write_feed(site_dir: str, stories: list) -> str:
    """Feed RSS do próprio Balanço (Fase 6.2): cada item linka a comparação."""
    from xml.sax.saxutils import escape
    out = ["""<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>""",
           f"<title>Balanço — todos os lados da notícia</title>",
           f"<link>{SITE_URL}/</link>",
           "<description>Histórias agrupadas por cobertura de esquerda, centro e direita.</description>",
           "<language>pt-BR</language>"]
    for s in stories[:30]:
        desc = (f"{s.get('summary', '')} "
                f"Cobertura: esquerda {s['pct']['L']}%, centro {s['pct']['C']}%, "
                f"direita {s['pct']['R']}% ({s['counts']['total']} veículos).")
        out.append(
            f"<item><title>{escape(s['title'])}</title>"
            f"<link>{SITE_URL}/?story={s['id']}</link>"
            f"<guid>{SITE_URL}/?story={s['id']}</guid>"
            f"<pubDate>{s.get('updated', '')}</pubDate>"
            f"<description>{escape(desc[:600])}</description></item>")
    out.append("</channel></rss>")
    dest = os.path.join(site_dir, "feed.xml")
    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return dest


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
