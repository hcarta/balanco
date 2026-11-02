#!/usr/bin/env python3
"""Balanço MVP — coleta RSS/sitemaps, agrupa stories, gera docs/data.json.

Viés é FIXO por fonte (posicionamento da publicação), sem análise por matéria.
O LLM é opt-in (--llm) e só deve ser usado quando explicitamente desejado.
"""
import argparse
import hashlib
import html
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


FACTUALITY_LEVELS = {"very_high", "high", "mixed", "low", "very_low"}
FETCHERS = {"rss", "sitemap"}
KINDS = {"br", "intl"}


def validate_sources(sources) -> list[str]:
    """Validação de schema de `sources.yaml` (Fase 4). Retorna erros."""
    errs, ids = [], set()
    if not isinstance(sources, list) or not sources:
        return ["sources.yaml: lista vazia ou inválida"]
    for i, s in enumerate(sources):
        where = f"fonte #{i} ({s.get('id', '?')})"
        if not isinstance(s, dict):
            errs.append(f"{where}: não é um mapa")
            continue
        sid = s.get("id")
        if not sid or not isinstance(sid, str):
            errs.append(f"{where}: id ausente")
        elif sid in ids:
            errs.append(f"{where}: id duplicado")
        else:
            ids.add(sid)
        if not s.get("name"):
            errs.append(f"{where}: nome ausente")
        if not (s.get("rss") or s.get("url")):
            errs.append(f"{where}: rss/url ausente")
        try:
            b = float(s.get("bias", 0))
        except (TypeError, ValueError):
            errs.append(f"{where}: bias não numérico")
        else:
            if not (-2.0 <= b <= 2.0):
                errs.append(f"{where}: bias {b} fora de [-2, 2]")
        if s.get("factuality") not in FACTUALITY_LEVELS:
            errs.append(f"{where}: factuality inválida "
                        f"({s.get('factuality')!r})")
        if s.get("fetcher", "rss") not in FETCHERS:
            errs.append(f"{where}: fetcher inválido ({s.get('fetcher')!r})")
        if s.get("kind", "br") not in KINDS:
            errs.append(f"{where}: kind inválido ({s.get('kind')!r})")
    return errs


def load_sources(path):
    with open(path, encoding="utf-8") as f:
        sources = yaml.safe_load(f)["sources"]
    errs = validate_sources(sources)
    if errs:
        raise ValueError("sources.yaml inválido:\n  " + "\n  ".join(errs))
    return sources


def fetch_all(sources, per_feed=30, store=None, window_h=72, run_ts="",
              workers=6):
    from concurrent.futures import ThreadPoolExecutor
    from collectors import collect_one
    from store import PER_SOURCE_CAP

    articles = []
    n_ok, n_err, n_new, n_dropped = 0, 0, 0, 0

    # Fase 4: coleta em paralelo por fonte; o processamento e a escrita do
    # cache ficam na thread principal, na ordem original das fontes, para a
    # saída continuar determinística.
    def _collect(s):
        try:
            return (s, collect_one(s, limit=per_feed if store is None else 2000,
                                   store=store), None)
        except Exception as ex:  # noqa: BLE001 - devolve o erro para o laço
            return (s, (None, None), ex)

    if workers and len(sources) > 1:
        with ThreadPoolExecutor(max_workers=min(workers, len(sources))) as ex:
            results = list(ex.map(_collect, sources))
    else:
        results = [_collect(s) for s in sources]

    for s, payload, col_err in results:
        try:
            if col_err is not None:
                raise col_err
            fresh, hs = payload
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
                # F-01/F-08: o cache pode ter itens antigos de loteria/esporte
                # que passaram antes do filtro; filtrar também o que veio dele.
                got = [a for a in got
                       if not excluded_section(a.get("section"))
                       and not excluded_title(a.get("title"))]
                n_window = store.count_recent(s["id"], window_h=window_h)
                status = hs.get("status", "ok")
                if hs.get("status") == "error" and got:
                    status = "stale"  # usa cache porque a rede falhou
                store.log_fetch(s["id"], run_ts, len(fresh), len(got),
                                status, hs.get("ms", 0),
                                "; ".join(hs.get("errors", [])),
                                n_window=n_window)
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


_EMB_BACKEND = None


def embed_matrix(docs, model_name: str = _EMB_NAME):
    """Embeddings MiniLM multilíngue normalizados.

    Prefere ONNX/fastembed (CI, sem torch); cai para sentence_transformers
    local; se nenhum existir, levanta — os chamadores já fazem fallback
    para TF-IDF.
    """
    global _EMB_MODEL, _EMB_BACKEND
    texts = [d.get("title", "") for d in docs]
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    try:
        from fastembed import TextEmbedding
        if (_EMB_BACKEND != "fastembed" or _EMB_MODEL is None
                or getattr(_EMB_MODEL, "_bname", None) != model_name):
            cache = os.environ.get("FASTEMBED_CACHE_PATH") or None
            kwargs = {"cache_dir": cache} if cache else {}
            fb_name = {
                "paraphrase-multilingual-MiniLM-L12-v2":
                    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            }.get(model_name, model_name)
            _EMB_MODEL = TextEmbedding(model_name=fb_name, **kwargs)
            _EMB_MODEL._bname = model_name
            _EMB_BACKEND = "fastembed"
        X = np.asarray(list(_EMB_MODEL.embed(texts, batch_size=32)),
                       dtype=np.float32)
        norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
        return X / norms
    except ImportError:
        pass
    try:
        from sentence_transformers import SentenceTransformer
        if (_EMB_BACKEND != "st" or _EMB_MODEL is None
                or getattr(_EMB_MODEL, "_bname", None) != model_name):
            _EMB_MODEL = SentenceTransformer(model_name)
            _EMB_MODEL._bname = model_name
            _EMB_BACKEND = "st"
        X = _EMB_MODEL.encode(texts, convert_to_numpy=True,
                              show_progress_bar=False)
        norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
        return X / norms
    except ImportError:
        raise RuntimeError("nem fastembed nem sentence_transformers instalados")


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


# F-04: coerência de cluster. O single-link cria cadeias (uma história de
# 140 artigos misturando fuga, G20 e carta golpista). Grupos grandes são
# validados contra o medoide; os ejetados são re-agrupados com limiar maior.
COHERE_MIN = 12          # só vale a pena olhar grupos deste tamanho
COHERE_TAU = 0.30        # similaridade mínima com o medoide
COHERE_RECLUSTER = 0.42  # limiar mais duro para os ejetados
COHERE_MAX_DEPTH = 6


_ENT_CACHE: dict[str, set] = {}


def _title_entities(title: str) -> set:
    e = _ENT_CACHE.get(title)
    if e is None:
        e = entities(title)
        _ENT_CACHE[title] = e
    return e


def _entity_anchor(a: dict, b: dict) -> bool:
    """Há nome próprio específico em comum? "eleição presidencial" não é âncora."""
    inter = _title_entities(a.get("title", "")) & \
        _title_entities(b.get("title", ""))
    return any(x not in ENTITY_GENERIC for x in inter)


def _near_duplicate(shared, toksets, i, j, s_ij) -> bool:
    """Título praticamente igual — dispensa âncora de entidade.

    Mantém o atalho de cobertura (títulos curtos), mas quem decide o veto de
    macro-tema é `_summary_conflict`, aplicado também aqui (exceto em cosseno
    altíssimo, que é duplicata real).
    """
    small = min(len(toksets[i]), len(toksets[j])) or 1
    return (len(shared) >= 4 and len(shared) / small >= 0.5) or s_ij >= 0.62


PAIR_FEATURE_NAMES = [
    "cos_tfidf", "cos_emb", "jaccard", "cov_short", "cov_long",
    "shared_all", "shared_spec", "shared_multi", "shared_numbers",
    "numbers_match", "same_section", "same_group", "dt_hours",
    "len_a", "len_b", "ent_first3_a", "ent_first3_b", "subject_match",
    "rule_fused",
]
_PAIR_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
_PAIR_MODEL = None


def _first3_ents(title: str) -> int:
    toks = tok(title)[:3]
    parts = {p for e in _title_entities(title) for p in e.split()}
    return 1 if any(t in parts for t in toks) else 0


def pair_features(a, b, cos, cos_emb=None, dt_hours=0.0,
                  section_a=None, section_b=None,
                  group_a=None, group_b=None, rule=None):
    """Vetor de features do gate de par (mesmo de ops/pair_features.py)."""
    ta, tb = a.get("title", ""), b.get("title", "")
    sa, sb = set(tok(ta)), set(tok(tb))
    shared = sa & sb
    union = sa | sb
    inter_ent = _title_entities(ta) & _title_entities(tb)
    na = set(_PAIR_NUM_RE.findall(ta))
    nb = set(_PAIR_NUM_RE.findall(tb))
    first3_a, first3_b = tok(ta)[:2], tok(tb)[:2]
    return {
        "cos_tfidf": round(float(cos), 4),
        "cos_emb": round(float(cos_emb), 4) if cos_emb is not None else -1.0,
        "jaccard": round(len(shared) / len(union), 4) if union else 0.0,
        "cov_short": round(len(shared) / min(len(sa), len(sb)), 4)
        if sa and sb else 0.0,
        "cov_long": round(len(shared) / max(len(sa), len(sb)), 4)
        if sa or sb else 0.0,
        "shared_all": len(shared),
        "shared_spec": len({w for w in shared if w not in ENTITY_GENERIC}),
        "shared_multi": len([e for e in inter_ent if " " in e]),
        "shared_numbers": len(na & nb),
        "numbers_match": 1 if (na and nb and na & nb) else 0,
        "same_section": 1 if (section_a and section_a == section_b) else 0,
        "same_group": 1 if (group_a and group_a == group_b) else 0,
        "dt_hours": round(float(dt_hours), 2),
        "len_a": len(sa),
        "len_b": len(sb),
        "ent_first3_a": _first3_ents(ta),
        "ent_first3_b": _first3_ents(tb),
        "subject_match": 1 if (first3_a and first3_b
                               and set(first3_a) & set(first3_b)) else 0,
        "rule_fused": 1 if rule in ("fused", "near_dup_ok") else 0,
    }


def load_pair_model(path: str):
    """Carrega o modelo JSON (F3). Sem chamada, o veto fica desligado."""
    global _PAIR_MODEL
    with open(path, encoding="utf-8") as f:
        _PAIR_MODEL = json.load(f)
    return _PAIR_MODEL


def pair_probability(model: dict, feats: dict) -> float:
    """Probabilidade de 'mesmo fato' (inferência só-numpy)."""
    names = model["features"]
    x = np.array([float(feats.get(k, 0.0)) for k in names], dtype=float)
    mu = np.array(model["mean"], dtype=float)
    sd = np.array(model["scale"], dtype=float)
    coef = np.array(model["coef"], dtype=float)
    z = float(((x - mu) / sd) @ coef + float(model["intercept"]))
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _summary_conflict(a: dict, b: dict, shared: set) -> bool:
    """Dois títulos parecidos, mas resumos que não falam da mesma coisa.

    Só vale quando os dois deks têm substância (>=4 tokens). Casos legítimos do
    mesmo fato costumam compartilhar número ou entidade multi-palavra; sem
    isso, e com dek sem sobreposição, o elo é de macro-tema, não de fato.
    """
    sa = a.get("summary") or ""
    sb = b.get("summary") or ""
    ta, tb = tok(sa), tok(sb)
    if len(ta) < 4 or len(tb) < 4:
        return False
    cov = _title_cov(set(ta), set(tb))
    if cov >= 0.05:
        return False
    inter = _title_entities(a.get("title", "")) & \
        _title_entities(b.get("title", ""))
    if any(" " in e and e not in ENTITY_GENERIC for e in inter):
        return False
    if set(_PAIR_NUM_RE.findall(a.get("title", ""))) & \
            set(_PAIR_NUM_RE.findall(b.get("title", ""))):
        return False
    return True


def _pair_decision(articles, toksets, S, Se, i, j, th, window_h):
    """Decisão de par com motivo (para auditoria F0; `_pair_ok` é o wrapper).

    Retorna (funde: bool, rule: str). `rule` é o estágio que decidiu:
    low_sim | near_dup_ok | no_entity | no_content | same_source |
    time_window | fused.
    """
    shared = toksets[i] & toksets[j]
    if len(shared) < 1:
        return False, "low_sim"
    pred = S[i, j] >= th and len(shared) >= 2
    if Se is not None and not pred and Se[i, j] >= 0.70 and len(shared) >= 1:
        pred = True  # híbrido: paráfrase semântica (Fase 2.2)
    if not pred:
        return False, "low_sim"
    near = _near_duplicate(shared, toksets, i, j, S[i, j])
    # veto de macro-tema: dois títulos parecidos com deks que não se tocam.
    # Cosseno >= 0,75 é duplicata real (mesmo título) — não veta.
    if float(S[i, j]) < 0.75 and _summary_conflict(articles[i], articles[j], shared):
        return False, "summary_conflict"
    # título praticamente igual dispensa as âncoras abaixo
    if not near:
        # dois fatos distintos compartilham vocabulário de tema ("eleição
        # presidencial", "guerra", "Rússia"); sem nome próprio em comum o
        # par não é a mesma notícia.
        if not _entity_anchor(articles[i], articles[j]):
            return False, "no_entity"
        # e o nome próprio sozinho não basta: "Papa Leão XIV vota" × "Papa
        # Leão XIV pede paz" são fatos diferentes. Precisa de conteúdo em
        # comum além das entidades (nomes/cargos/siglas não são assunto).
        ents = (_title_entities(articles[i].get("title", ""))
                | _title_entities(articles[j].get("title", "")))
        if not (shared - ents):
            return False, "no_content"
    else:
        # passou pelo atalho de quase-duplicata; ainda valida fonte/tempo
        pass
    si, sj = articles[i].get("source_id"), articles[j].get("source_id")
    if si is not None and si == sj:
        # mesma fonte: exige mais evidência (Fase 2.3)
        ti, tj = tok(articles[i]["title"]), tok(articles[j]["title"])
        if len(ti) >= 2 and len(tj) >= 2 and ti[:2] == tj[:2]:
            return False, "same_source"  # série da casa ("Pinguins X", "VÍDEOS: Jornal ...")
        same_sec = bool(articles[i].get("section")) and \
            articles[i].get("section") == articles[j].get("section")
        floor = th + (0.12 if same_sec else 0.10)
        if S[i, j] < floor or len(shared) < 3:
            return False, "same_source"
    dt = abs(articles[i]["ts"] - articles[j]["ts"]) / 3600
    w = pair_window(articles[i].get("section"), articles[j].get("section"),
                    window_h)
    if dt > w:
        return False, "time_window"
    rule = "near_dup_ok" if _near_duplicate(shared, toksets, i, j, S[i, j]) \
        else "fused"
    # F3 (veto): a regra léxica fundiria; o modelo pode derrubar elos fracos
    # que encadeiam fatos distintos (ex.: safra Trump × Papa).
    if _PAIR_MODEL is not None:
        feats = pair_features(
            articles[i], articles[j], float(S[i, j]),
            float(Se[i, j]) if Se is not None else None,
            dt_hours=dt,
            section_a=articles[i].get("section"),
            section_b=articles[j].get("section"),
            group_a=articles[i].get("group") or articles[i].get("source_id"),
            group_b=articles[j].get("group") or articles[j].get("source_id"),
            rule=rule)
        cutoff = float(_PAIR_MODEL.get("veto_threshold", 0.25))
        if pair_probability(_PAIR_MODEL, feats) < cutoff:
            return False, "veto_model"
    return True, rule


def _pair_ok(articles, toksets, S, Se, i, j, th, window_h):
    """Decisão de par (extraída para o cluster e a coerência usarem a mesma)."""
    ok, _ = _pair_decision(articles, toksets, S, Se, i, j, th, window_h)
    return ok


def _components(indices, articles, toksets, S, Se, th, window_h):
    idx = list(indices)
    parent = {i: i for i in idx}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p, i in enumerate(idx):
        for j in idx[p + 1:]:
            if _pair_ok(articles, toksets, S, Se, i, j, th, window_h):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    out: dict[int, list] = {}
    for i in idx:
        out.setdefault(find(i), []).append(i)
    return list(out.values())


def _cohere(groups, articles, toksets, S, Se, window_h):
    def split(g, depth=0):
        if len(g) < COHERE_MIN or depth >= COHERE_MAX_DEPTH:
            return [g]
        sub = S[np.ix_(g, g)]
        med = g[int(np.argmax(sub.mean(axis=1)))]
        keep = [i for i in g if i == med or S[med, i] >= COHERE_TAU]
        if len(keep) == len(g):
            return [g]
        out = [keep]
        eject = [i for i in g if i not in set(keep)]
        for subg in _components(eject, articles, toksets, S, Se,
                                COHERE_RECLUSTER, window_h):
            out.extend(split(subg, depth + 1))
        return out

    out = []
    for g in groups:
        out.extend(split(g))
    return out


def cluster(articles, thresh=0.38, window_h=48, use_embed=False,
            audit_path=None):
    """Agrupa artigos em histórias. `audit_path` (F0) é opt-in: sem ele o
    resultado é byte-idêntico ao anterior."""
    import os as _os
    if audit_path is None:
        audit_path = _os.environ.get("BALANCO_AUDIT") or None
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

    # F-14: candidatos via matriz (já calculada), não O(n²) em Python.
    cand = S >= thresh
    if Se is not None:
        cand = cand | (Se >= 0.70)
    ii, jj = np.where(np.triu(cand, k=1))
    _audit = [] if audit_path else None
    weak = []
    strong_nb: dict[int, set] = {}

    def _audit_rec(i, j, ok, rule):
        if _audit is None:
            return
        ai, aj = articles[i], articles[j]
        try:
            dt_h = abs(ai.get("ts", 0) - aj.get("ts", 0)) / 3600
        except TypeError:
            dt_h = None
        _audit.append({
            "a": ai.get("title", ""), "b": aj.get("title", ""),
            "source_a": ai.get("source_id"), "source_b": aj.get("source_id"),
            "section_a": ai.get("section"), "section_b": aj.get("section"),
            "dt_h": round(dt_h, 2) if dt_h is not None else None,
            "cos": round(float(S[i, j]), 4),
            "cos_emb": round(float(Se[i, j]), 4) if Se is not None else None,
            "shared": sorted(toksets[i] & toksets[j]),
            "ents": sorted(_title_entities(ai.get("title", ""))
                           & _title_entities(aj.get("title", ""))),
            "decision": "fused" if ok else "rejected",
            "rule": rule,
        })

    # 1) pares fortes: fundem direto
    for i, j in zip(ii.tolist(), jj.tolist()):
        ok, rule = _pair_decision(articles, toksets, S, Se, i, j, thresh,
                                  window_h)
        if ok and float(S[i, j]) >= STRONG_LINK:
            union(i, j)
            strong_nb.setdefault(i, set()).add(j)
            strong_nb.setdefault(j, set()).add(i)
            _audit_rec(i, j, True, rule)
        elif ok:
            weak.append((i, j, rule))
        else:
            _audit_rec(i, j, False, rule)

    # 2) elos fracos: só barram quando os DOIS lados já estão ancorados em
    # clusters fortes distintos e não têm vizinho forte em comum. Se um lado
    # está isolado, o elo é a única forma de anexá-lo (história de 2 fontes).
    for i, j, rule in weak:
        ni, nj = strong_nb.get(i, set()), strong_nb.get(j, set())
        if not ni or not nj or (ni & nj):
            union(i, j)
            _audit_rec(i, j, True, "weak_bridge")
        else:
            _audit_rec(i, j, False, "weak_no_bridge")
    if _audit is not None:
        import json as _json
        _os.makedirs(_os.path.dirname(_os.path.abspath(audit_path)),
                     exist_ok=True)
        with open(audit_path, "w", encoding="utf-8") as f:
            for rec in _audit:
                f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
    groups: dict[int, list] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    # F-04: valida grupos grandes contra o medoide e separa ejetados
    groups_out = _cohere(list(groups.values()), articles, toksets, S, Se, window_h)
    # ordena grupos por tamanho e recência
    out = sorted(groups_out, key=lambda g: (-len(g), -max(articles[i]["ts"] for i in g)))
    return out


# Categorias que não são "pauta de capa": editorial, opinião, serviço,
# carros, receitas e esporte. Determinístico e ajustável.
FRONT_SKIP = re.compile(
    r"^\s*editorial\b|\beditorial:"
    r"|^\s*coluna\b|\ban[aá]lise\b"
    r"|como rastrear|passo a passo|receitas?\b|chef\b|moqueca|cheesecake"
    r"|\bSUV\b|convers[ií]vel|aston martin|t-cross|creta|aceleramos"
    r"|f[oó]rmula 1|futebol|brasileir[aã]o|libertadores"
    r"|fantasiar de sem-teto|v[oô]lei|novela|\bbb\b|famosos|celebridades",
    re.I)
# coluna/blog/opinião/podcast/vídeo pela URL (não só pelo título)
FRONT_SKIP_URL = re.compile(
    r"/(esportes?|futebol|olimpiadas?|nba|f1|automobilismo|volei|v[oô]lei)/"
    r"|/(novelas?|celebridades|entretenimento|cinema|musica|moda|gastronomia"
    r"|guloseimas|teatro|horoscopo|diversao)/"
    r"|/(ilustrada|f5|pop)/"
    r"|/(colunas?|colunistas?|blogs?|opiniao|pulsa|podcasts?|videos?)/", re.I)

# Pautas editoriais: conceito -> regex. A ordem importa (específico antes do
# genérico). É um lexicon pequeno, mantível e sem LLM.
FRONT_CONCEPTS = [
    ("Eleição EUA / Trump", re.compile(
        r"midterms?|elei[cç][aã]o.{0,40}(eua|estados unidos)|democratas?"
        r"|congresso dos eua|senado dos eua|\btrump\b|\bmusk\b"
        r"|votos antecipados|corrida eleitoral|elei[cç][aã]o legislativa", re.I)),
    ("Lula / juros e economia", re.compile(
        r"\bselic\b|\bdurigan\b|\bcopom\b|\bjuros\b|\bfiscal\b"
        r"|mercado financeiro|lula empodera", re.I)),
    ("Flávio Bolsonaro", re.compile(
        r"fl[aá]vio bolsonaro|fuga de fl[aá]vio|senadores derrotados", re.I)),
    ("Reforma eleitoral", re.compile(
        r"reforma eleitoral|puxadores de voto", re.I)),
    ("Tarcísio / Linha 6", re.compile(r"tarc[ií]sio|linha 6", re.I)),
    ("Binance", re.compile(r"binance", re.I)),
    ("Ataque hacker / freezers", re.compile(
        r"supermercados?[^.]{0,60}freezers?|freezers?[^.]{0,60}supermercados?"
        r"|freezer[^.]{0,40}(hacker|temperatura|invas)", re.I)),
    ("Queda de avião", re.compile(
        r"queda de avi[aã]o|\bavi[aã]o cai|copilota|asa-delta|queda de jato",
        re.I)),
    ("Inadimplência", re.compile(r"inadimpl[eê]ncia|serasa", re.I)),
    ("Obesidade / SUS", re.compile(r"obes|\bsus\b", re.I)),
    ("Vale-refeição", re.compile(r"vale-refei|vale-alimenta", re.I)),
    ("Argentina / Milei", re.compile(r"\bmilei\b|argentin", re.I)),
    ("Irã / Hormuz", re.compile(r"\bir[aã]\b|\bhormuz\b|\bormuz\b", re.I)),
]

# Capas dos jornais de referência: peso editorial para o "Em foco".
# `sel` é o contêiner das manchetes principais; `kind` diz como extrair.
FRONT_PAGES = {
    "O Globo": {"url": "https://oglobo.globo.com/",
                "sel": ".manchetes__left a", "kind": "anchor"},
    "Estadão": {"url": "https://www.estadao.com.br/",
                "sel": "[class*='styles__TagStyled'][class*='col-lg-8'] h1,"
                       "[class*='styles__TagStyled'][class*='col-lg-8'] h2,"
                       "[class*='styles__TagStyled'][class*='col-lg-8'] h3",
                "kind": "heading"},
    "Folha de S.Paulo": {"url": "https://www.folha.uol.com.br/",
                         "sel": ".col--md-3-4 h1, .col--md-3-4 h2,"
                                " .col--md-3-4 h3", "kind": "heading"},
    "G1": {"url": "https://g1.globo.com/",
           "sel": ".feed-post-body-title", "kind": "heading"},
    "UOL": {"url": "https://www.uol.com.br/",
            "sel": ".headlineMain__link, .headlineHorizontal__link",
            "kind": "heading"},
    "CNN Brasil": {"url": "https://www.cnnbrasil.com.br/", "sel": "a",
                   "kind": "heading"},
}


def _front_items(html_text: str, cfg: dict, limit: int = 10) -> list[dict]:
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "lxml")
    out, seen = [], set()
    for el in soup.select(cfg["sel"]):
        if cfg["kind"] == "anchor":
            a = el
            title = el.get_text(" ", strip=True)
        else:
            a = el if el.name == "a" else (el.find_parent("a") or el.find("a"))
            hh = el if el.name in ("h1", "h2", "h3") else el.find(["h1", "h2", "h3"])
            title = (hh or el).get_text(" ", strip=True)
        title = re.sub(r"\s+", " ", title or "").strip()
        link = urljoin(cfg["url"], a.get("href", "")) if a else ""
        if len(title) < 25 or title in seen:
            continue
        if not link or link.rstrip("/") == cfg["url"].rstrip("/"):
            continue
        seen.add(title)
        out.append({"title": title, "link": link})
        if len(out) >= limit:
            break
    return out


def fetch_front_page(key: str, timeout: int = 20) -> list[dict]:
    """Manchetes da capa (título + link), na ordem, filtradas por categoria."""
    import requests
    cfg = FRONT_PAGES.get(key)
    if not cfg:
        return []
    try:
        r = requests.get(cfg["url"], timeout=timeout,
                         headers={"User-Agent": "Balanco/0.2 (+news aggregator; local)"})
        html_text = r.content.decode("utf-8", errors="replace")
    except requests.RequestException as ex:
        print(f"  [aviso] capa {key}: rede indisponível ({type(ex).__name__})")
        return []
    except Exception as ex:
        print(f"  [aviso] capa {key}: {type(ex).__name__}: {ex}")
        return []
    # erro de parser/dependência deve aparecer no log, não virar capa vazia
    items = _front_items(html_text, cfg)
    out = []
    for it in items:
        if FRONT_SKIP.search(it["title"]):
            continue
        if len(tok(it["title"])) < 4:
            continue
        if FRONT_SKIP_URL.search(it.get("link", "")):
            continue
        out.append(it)
    return out


# Pertença à pauta: o lead usa 0,50/0,40 (acima); as demais histórias do
# feed usam limiar um pouco mais largo para dar contexto sem puxar outro fato.
PAUTA_COV = 0.45
PAUTA_COV_ENTITY = 0.35


# Refinamento de pertença: o conceito sozinho é largo ("Trump" também
# aparece em Irã, Groenlândia, jornal). A história precisa citar a dimensão
# que define a pauta, senão vira "veja também" enganoso.
PAUTA_REQUIRE = {
    "Eleição EUA / Trump": re.compile(
        r"midterm|elei[cç][aã]o|votos? antecipad|democratas?|republicanos?"
        r"|corrida eleitoral|congresso|senado", re.I),
    "Argentina / Milei": re.compile(
        r"milei|oposi[cç][aã]o|governo|elei[cç][aã]o|diplomat|itamaraty"
        r"|fl[aá]vio|casa rosada", re.I),
}

# Pertença à pauta: proporção mínima de matérias da história que citam o
# conceito. Evita que uma matéria lateral arraste um cluster inteiro.
PAUTA_MIN_RATIO = 0.25
PAUTA_MIN_ARTS = 2


def _theme_story(theme_titles, stories, toks):
    """Melhor história para um tema de capa (títulos + entidades)."""
    best, score = None, 0.0
    for s in stories:
        for ht in theme_titles:
            hset = set(tok(ht))
            if len(hset) < 3:
                continue
            he = _title_entities(ht)
            for st, se in toks[id(s)]:
                if len(st) < 3:
                    continue
                shared = hset & st
                if len(shared) < 2:
                    continue
                cov = len(shared) / max(1, min(len(hset), len(st)))
                spec = {e for e in (he & se) if e not in ENTITY_GENERIC}
                if cov >= 0.5 or (spec and cov >= 0.4):
                    if cov > score:
                        best, score = s, cov
    return best, score


def attach_front_pages(stories, desks=None, source_meta=None, stats=None):
    """Agenda predominante das capas: conceito -> jornais -> histórias.

    Retorna (stories, front_only, pautas). `front_only` são pautas de capa
    que não existem no feed (1 jornal), para os 4 slots da capa; `pautas`
    liga cada pauta de capa às histórias do feed (P1).
    """
    source_meta = source_meta or {}
    desks = desks if desks is not None else {
        k: fetch_front_page(k) for k in FRONT_PAGES}
    if stats is not None:
        stats.update({k: len(v) for k, v in desks.items()})
    heads = []
    for source, items in desks.items():
        pos = 0
        for it in items:
            title = it.get("title", "")
            if FRONT_SKIP.search(title) or len(tok(title)) < 4:
                continue
            pos += 1
            heads.append({"source": source, "position": pos,
                          "title": title, "link": it.get("link", "")})
    for h in heads:
        h["concept"] = next((label for label, rx in FRONT_CONCEPTS
                             if rx.search(h["title"])), None)
    groups = {}
    for h in heads:
        if h["concept"]:
            groups.setdefault(h["concept"], []).append(h)
    toks = {id(s): [(set(tok(a.get("title", ""))),
                     _title_entities(a.get("title", "")))
                    for a in s.get("articles", [])] for s in stories}
    for s in stories:
        s["front"] = []
    label_rx = dict(FRONT_CONCEPTS)
    # P1: pertença pelo suporte do conceito nas matérias da história. Um
    # cluster grande precisa de uma fatia mínima de matérias no tema; uma
    # matéria lateral sozinha não arrasta o cluster inteiro.
    members_by_label = {}
    for label in groups:
        rx = label_rx[label]
        req = PAUTA_REQUIRE.get(label)
        members = []
        for s in stories:
            arts = s.get("articles", [])
            n = sum(1 for a in arts
                    if rx.search(a.get("title", "") or "")
                    and (req is None or req.search(a.get("title", "") or "")))
            if n < PAUTA_MIN_ARTS:
                continue
            ratio = n / max(1, len(arts))
            if ratio >= PAUTA_MIN_RATIO:
                members.append((s, n, round(ratio, 2)))
        members.sort(key=lambda x: (-x[2], -x[1]))
        members_by_label[label] = members
    # Lead: melhor casamento lexical da capa; sem ele, a história com mais
    # matérias no tema (assim a pauta ainda entrega contexto ao leitor).
    leads = {}
    for label, items in groups.items():
        members = members_by_label.get(label, [])
        # o lead sai das histórias confirmadas no tema (nunca de outra pauta)
        pool = [s for s, _, _ in members] or stories
        story, score = _theme_story([h["title"] for h in items], pool, toks)
        if story is None and members:
            story, score = members[0][0], 0.0
        leads[label] = (story, score)
    # Cada história pertence a uma só pauta: a de maior suporte no tema.
    assigned = {}
    for label, members in members_by_label.items():
        for s, n, ratio in members:
            cur = assigned.get(s["id"])
            if cur is None or (ratio, n) > cur[0]:
                assigned[s["id"]] = ((ratio, n), label)
    # o lead nunca fica fora da própria pauta
    for label, (story, _) in leads.items():
        if story is not None:
            assigned[story["id"]] = ((1.0, 10 ** 6), label)
    ids_by_label = {}
    for sid, (_, label) in assigned.items():
        ids_by_label.setdefault(label, []).append(sid)
    pautas, front_only = [], []
    for label, items in groups.items():
        by = {}
        for h in items:
            cur = by.get(h["source"])
            if cur is None or h["position"] < cur["position"]:
                by[h["source"]] = h
        entries = sorted(by.values(), key=lambda x: x["position"])
        w = sum(1.0 if e["position"] <= 3 else
                0.7 if e["position"] <= 8 else 0.4 for e in entries)
        story, score = leads[label]
        key = re.sub(r"\W+", "-", label.lower()).strip("-")
        pauta = {"key": key, "label": label, "n_sources": len(by),
                 "best_position": min(e["position"] for e in entries),
                 "sources": [{"source": e["source"],
                              "position": e["position"],
                              "title": e["title"], "link": e["link"]}
                             for e in entries],
                 "front_score": round(w, 2),
                 "story_id": story["id"] if story else None,
                 "story_ids": sorted(ids_by_label.get(label, [])),
                 "lead": {"source": entries[0]["source"],
                          "position": entries[0]["position"],
                          "title": entries[0]["title"],
                          "link": entries[0]["link"]}}
        if story:
            story["front"] = [{"source": e["source"],
                               "position": e["position"],
                               "headline": e["title"][:140],
                               "match": round(score, 2)} for e in entries]
            story["front_score"] = round(w, 2)
            pauta["coverage"] = story["counts"]["total"]
        else:
            lead = entries[0]
            meta = source_meta.get(lead["source"], {}) or {}
            bias = float(meta.get("bias", 0) or 0)
            b = bucket(bias)
            counts = {k: 0 for k in BUCKETS}
            counts[b] = 1
            pct = {k: 0 for k in BUCKETS}
            pct[b] = 100
            fs = {"id": "fp-" + key, "title": lead["title"], "summary": "",
                  "articles": [{"source": lead["source"],
                                "title": lead["title"], "link": lead["link"],
                                "bucket": b, "bias": bias,
                                "piece_kind": "hard_news"}],
                  "counts": {**counts, "total": 1, "independent": 1,
                             "groups": counts, "frames": 0, "articles": 1},
                  "pct": pct, "avg_bias": round(bias, 2),
                  "blindspot": None, "updated": "",
                  "front": pauta["sources"], "front_score": round(w, 2),
                  "front_only": True, "topic": label,
                  "recent": {"n_6h": 1, "n_24h": 1}}
            pauta["pseudo_id"] = fs["id"]
            pauta["coverage"] = 1
            front_only.append(fs)
        pautas.append(pauta)
    by_id = {s["id"]: s for s in stories}
    fo_by_id = {fs["id"]: fs for fs in front_only}
    for p in pautas:
        p["n_stories"] = len(p["story_ids"])
        p["coverage_total"] = (
            sum(by_id[i]["counts"]["total"] for i in p["story_ids"]
                if i in by_id) if p["story_ids"] else p.get("coverage", 1))
        # P3: viés agregado da pauta. Uma matéria por grupo editorial (o viés
        # do grupo é a média das suas matérias na pauta), para que um veículo
        # com várias histórias não pese mais que os demais.
        srcs = [by_id[i] for i in p["story_ids"] if i in by_id]
        if not srcs and p.get("pseudo_id"):
            srcs = [fo_by_id[p["pseudo_id"]]]
        cov = [a for st in srcs for a in st.get("articles", [])
               if not a.get("piece_kind") or a["piece_kind"] in COVERAGE_KINDS]
        gc, ind, avg = independent_counts(cov, "bias")
        p["counts"] = {**gc, "total": len(cov), "independent": ind}
        p["pct"] = {b: (round(100 * gc[b] / ind) if ind else 0)
                    for b in BUCKETS}
        p["avg_bias"] = round(avg, 2)
        p["blindspot"] = blindspot_of5(*[gc[b] for b in BUCKETS])
        p["n_articles"] = len(cov)
        p["n_groups"] = ind
    pautas.sort(key=lambda p: (-p["n_sources"], p["best_position"],
                               -p["n_stories"], -p["coverage_total"]))
    # marca cada história com a sua pauta (uma só, a de melhor suporte)
    for p in pautas:
        for sid in p["story_ids"]:
            s = by_id.get(sid)
            if s is None:
                continue
            s["pauta"] = p["label"]
            s["pauta_key"] = p["key"]
            s["pauta_n_stories"] = p["n_stories"]
            # P4: o conceito de capa vira o rótulo do hub ("Outros ângulos");
            # o hub por entidade segue como fallback quando não há pauta.
            if p["n_stories"] >= 2:
                s["hub"] = {"key": "pauta:" + p["key"], "label": p["label"],
                            "size": p["n_stories"], "concept": True}
    # destaque das histórias (capa + cobertura + recência)
    for s in stories:
        w = s.get("front_score", 0)
        s["front_score"] = round(w, 2)
    max_total = max((s["counts"]["total"] for s in stories), default=1) or 1
    max_rec = max((s.get("recent", {}).get("n_6h", 0) for s in stories),
                  default=0) or 1
    for s in stories:
        nf = min(s.get("front_score", 0) / 2.0, 1.0)
        nt = s["counts"]["total"] / max_total
        nr = s.get("recent", {}).get("n_6h", 0) / max_rec
        s["destaque"] = round(0.55 * nf + 0.30 * nt + 0.15 * nr, 3)
    # destaque das pautas de capa sem história (cobertura = 1)
    for fs in front_only:
        nf = min(fs["front_score"] / 2.0, 1.0)
        fs["destaque"] = round(0.55 * nf + 0.30 * (1 / max_total)
                               + 0.15 * (1 / max_rec), 3)
    return stories, front_only, pautas


def blindspot_of(l: int, c: int, r: int):
    """Blindspot na assinatura de 3 blocos (compatibilidade/testes)."""
    return blindspot_of5(l, 0, c, 0, r)


def blindspot_of5(l: int, cl: int, c: int, cr: int, r: int):
    """Blindspot com 5 faixas; agrega blocos (L+CL) e (CR+R).

    3+ coberturas; tolerância de 15%; só-centro continua None.
    """
    left = l + cl
    right = r + cr
    tot = left + c + right
    if tot < 3:
        return None
    left_out = left / tot <= 0.15
    right_out = right / tot <= 0.15
    if left_out and right_out:
        return None  # só o centro cobre: sem viés em jogo
    if left_out:
        return "left"
    if right_out:
        return "right"
    return None


# PLAN_FINAL Fase 2: 5 colunas (aproximando Ground.news). Uma constante só.
BIAS_EDGES = (-0.8, -0.3, 0.3, 0.8)   # L | CL | C | CR | R
BUCKETS = ("L", "CL", "C", "CR", "R")

# A-4 (cluster de tópico): single-link encadeia fatos via elo fraco.
# Pares fortes fundem direto; elos fracos (0,38–0,45) só entram se os dois
# lados já estiverem ancorados num mesmo vizinho forte.
STRONG_LINK = 0.45
WEAK_BRIDGE_MIN = 1


def bucket(score):
    """Classifica o viés em 5 faixas: L, CL, C, CR, R."""
    lo_l, lo_cl, lo_cr, lo_r = BIAS_EDGES
    if score <= lo_l:
        return "L"
    if score <= lo_cl:
        return "CL"
    if score < lo_cr:
        return "C"
    if score < lo_r:
        return "CR"
    return "R"


def _group_key(x):
    return x.get("group") or x.get("source_id") or x.get("source") or "?"


def independent_counts(arts, bias_key="bias"):
    """Conta grupos editoriais, não matérias (A-7).

    G1 + O Globo + Valor = 1 grupo (Globo); BBC Brasil/World = 1; NYT
    World/Tecnologia = 1. O bucket do grupo é o do viés médio das matérias.
    """
    by = {}
    for x in arts:
        by.setdefault(_group_key(x), []).append(x)
    gc = {b: 0 for b in BUCKETS}
    biases = []
    for xs in by.values():
        vals = [float(x.get(bias_key, 0) or 0) for x in xs]
        gb = sum(vals) / len(vals) if vals else 0.0
        gc[bucket(gb)] += 1
        biases.append(gb)
    ind = sum(gc.values())
    avg = sum(biases) / len(biases) if biases else 0.0
    return gc, ind, avg


# Editorias fora da edição (o foco é poder, economia e sociedade)
EXCLUDED_SECTIONS = {"esportes", "esporte", "futebol", "astrologia", "loterias"}

# Conteúdo de serviço mora em editorias genéricas: filtra pelo título
EXCLUDED_TITLE = re.compile(
    r"lotof[aá]cil|mega-sena|megasena|lotomania|dupla\ssena|timemania"
    r"|\bquina\b[^.]{0,40}(sorteio|resultado|concurso|dezenas)"
    r"|hor[oó]scopo|mapa\s+astral|previs[aã]o\s+do\s+tempo|fases?\s+da\s+lua"
    r"|\bloteria\b.{0,40}(sorteio|resultado|concurso|pr[eê]mio)"
    # F-08: rundown de vídeo/programa ao vivo não é notícia de cobertura
    r"|^\s*v[ií]deos?\s*:|^\s*assist[ai]\s+ao\s+programa|\bao\s+vivo\b"
    # serviço local: cemitérios/visitação de Finados e bandeira tarifária
    r"|\bcemit[eé]rios?\b.{0,80}\b(finados|visitantes|missas)\b"
    r"|\bbandeira (verde|amarela|vermelha)\b.{0,60}\b(energia|conta|tarifa)\b"
    # futebol (clubes, competições, transferências) — fora da edição
    r"|\bfutebol\b|\bfutebol\w*\b|\bflamengo\b|\bcorinthians\b|\bpalmeiras\b"
    r"|\bsantos fc\b|\bs[aã]o paulo fc\b|\bsele[cç][aã]o brasileira\b"
    r"|\blibertadores\b|\bbrasileir[aã]o\b|\bbrasileir[aã]o s[eé]rie\b"
    r"|\bcopa do mundo\b|\bcopa am[eé]rica\b|\bchampions league\b"
    r"|\bpremier league\b|\bla liga\b|\breal madrid\b|\bbarcelona\b"
    r"|\bfluminense\b|\bvasco\b|\bbotafogo\b|\bgr[eê]mio\b"
    r"|\batl[eé]tico[- ]mg\b|\bathletico\b"
    r"|\bneymar\b|\bmessi\b|\bmbapp[eé]\b|\bhaaland\b|\bvin[ií]cius j[uú]nior\b"
    r"|\bhat[- ]trick\b|\bgol de\b|\bp[eê]nalti\b|\bcartão vermelho\b"
    r"|\bcampeonato brasileiro\b|\btabela do brasileir[aã]o\b"
    r"|\b(chuva|calor|frio|clima|temperatura)\b.{0,60}\bprevis[aã]o\b"
    r"|previs[aã]o\b.{0,60}\b(tempo|chuva|calor|frio|clima|temperatura)\b"
    # calendário de pagamento/benefício é serviço, não notícia de política
    r"|\bcalend[aá]rio\b.{0,80}\b(pagamentos?|benef[ií]cios?|bolsa\s+fam[ií]lia"
    r"|inss|aux[ií]lio|abono|fgts|\bpis\b|13[ºo°]|aposentad|seguro-desemprego"
    r"|sal[aá]rio)\w*\b"
    r"|\b(bolsa\s+fam[ií]lia|inss|aux[ií]lio|abono|fgts|benef[ií]cio)\b.{0,60}"
    r"\bcalend[aá]rio\b"
    r"|\bdatas?\s+de\s+pagamentos?\b.{0,60}\b(benef[ií]cios?|bolsa\s+fam[ií]lia"
    r"|inss|aux[ií]lio|abono|fgts|sal[aá]rio)\b",
    re.I)


def excluded_section(raw: str | None) -> bool:
    return _norm_sec(raw) in EXCLUDED_SECTIONS


# Previsão/alerta meteorológico é serviço. Evento com impacto (alagamento,
# ilhados, sem luz) continua sendo notícia e não cai neste filtro.
WEATHER_SERVICE = re.compile(
    r"\bprevis[aã]o\b.{0,60}\b(tempo|chuva|chuvas|chover|calor|frio|clima"
    r"|temperatura|temporais?|semana|dias)\b"
    r"|\b(chuva|chuvas|chover|calor|frio|clima|temperatura|sol)\b.{0,60}\bprevis[aã]o\b"
    r"|\b(alerta|avisos?)\b.{0,40}\b(chuva|chuvas|tempestade|temporal|vendaval|umidade"
    r"|frio|calor|rajadas)\b"
    r"|\b(inmet|defesa civil)\b.{0,60}\balerta\b"
    r"|\b(calor|frio|sol)\b.{0,40}\b(chuva|chuvas|chover|pancadas|temporais?)\b"
    r"|\b(chuva|chuvas|chover|pancadas|temporais?)\b.{0,40}\b(calor|frio|sol|feriado"
    r"|fim de semana)\b"
    r"|\bchuvas?\b.{0,40}\b(acima|abaixo) da m[eé]dia\b"
    r"|\bchuvas? (fortes|intensas)\b.{0,40}\b(pa[ií]s|virada|m[eê]s|semana)\b"
    r"|\btemporais?\b.{0,40}\b(brasil|pa[ií]s|novembro|semana|fim de semana)\b",
    re.I)

WEATHER_IMPACT = re.compile(
    r"alagament|desabament|desabrigad|desalojad|ilhad|enchente|inunda"
    r"|\bmorreu?\b|\bmort[eo]s?\b|v[ií]timas|sem luz|falta de (luz|energia)"
    r"|destru|interditad|queda de [aá]rvore|cancelad",
    re.I)


def excluded_title(title: str | None) -> bool:
    t = title or ""
    if EXCLUDED_TITLE.search(t):
        return True
    return bool(WEATHER_SERVICE.search(t) and not WEATHER_IMPACT.search(t))


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
    # F-10: editorias genéricas/de idioma não viram filtro
    "geral": "", "noticias": "", "noticia": "", "ultimas": "",
    "pt-br": "", "pt_br": "", "br": "", "portuguese": "",
    "pop": "Cultura", "pop-arte": "Cultura",
    "agro": "Agro", "carros": "Carros", "cinema": "Cinema", "musica": "Música",
    "viagem": "Viagem", "comida": "Comida", "pets": "Pets", "consumo": "Consumo",
    "carreira": "Carreira", "trabalho": "Trabalho", "ilustrada": "Cultura",
    "folhinha": "Cultura", "guia": "Guia", "play": "Cultura", "style": "Cultura",
    "voceviu": "Cultura", "pulsa": "Cultura", "rioshow": "Cultura",
    "minha-serie": "Cultura", "emais": "Cultura", "diversao": "Cultura",
    "nacional": "Brasil", "republica": "Brasil", "cotidiano": "Cotidiano",
    "meio-ambiente": "Ambiente", "ambiente": "Ambiente",
    "legislacao": "Política", "poder-brasil": "Poder",
    "poder-governo": "Poder", "poder-gente": "Poder",
    "poder-sportsmkt": "Poder", "poder-internacional": "Poder",
    "equilibrio": "Saúde", "equilibrioesaude": "Saúde",
    "folha-social-mais": "Sociedade", "ela": "Sociedade",
    "patrocinado": "",
    # UFs viram "Brasil" no filtro (não são editorias)
    **{uf: "Brasil" for uf in (
        "ac","al","am","ap","ba","ce","df","es","go","ma","mg","ms","mt",
        "pa","pb","pe","pi","pr","rj","rn","ro","rr","rs","sc","se","to")},
}


def section_label(raw: str | None) -> str:
    key = _norm_sec(raw)
    # F-10: whitelist; seção desconhecida não vira filtro ("Ac", "Agro"...)
    return SECTION_LABELS.get(key, "")


def framing_terms(coverage, top_n=3, min_count=2, alpha=0.5):
    """A-9: termos distintivos por bucket (log-odds com suavização).

    Compara como cada lado (L/C/R) intitulou o mesmo fato. Só cobertura,
    só tokens com >= min_count na história; ignora bucket vazio ou história
    de lado único. Retorna {"L": [...], "C": [...], "R": [...]}.
    """
    buckets = BUCKETS
    toks = {b: [] for b in buckets}
    for x in coverage:
        if x.get("bucket") in toks:
            toks[x["bucket"]] += tok(x.get("title", ""))
    present = [b for b in buckets if toks[b]]
    if len(present) < 2:
        return {}
    df = Counter(w for x in coverage for w in set(tok(x.get("title", ""))))
    vocab = [w for w, c in df.items() if c >= min_count]
    if not vocab:
        return {}
    n = {b: len(toks[b]) or 1 for b in buckets}
    out = {}
    for b in buckets:
        if not toks[b]:
            continue
        cb = Counter(toks[b])
        scored = []
        for w in vocab:
            rest = sum(1 for o in buckets if o != b for t in toks[o] if t == w)
            lo = math.log((cb.get(w, 0) + alpha) / (n[b] + alpha * len(vocab)))
            lo -= math.log((rest + alpha) / (sum(n[o] for o in buckets if o != b)
                                             + alpha * len(vocab)))
            if cb.get(w, 0) >= min_count:
                scored.append((lo, w))
        out[b] = [w for _, w in sorted(scored, reverse=True)[:top_n]]
    return out


def rep_score(item: dict, meta: dict) -> float:
    """Pontua o melhor título representante da história (Fase 2.4).

    Prefere informativo e neutro: tamanho saudável, fonte de factualidade alta,
    sem clickbait (?, !, CAIXA ALTA) nem excesso de aspas.
    """
    t = item.get("title", "")
    s = min(len(t), 140) / 140
    sec = _norm_sec(item.get("section"))
    if sec in LONGFORM_SECTIONS:
        s -= 0.25  # opinião/blog/coluna não é a melhor manchete factual
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


def _stable_id(items):
    """F-03: id ancorado no artigo mais antigo por `first_seen`.

    IDs posicionais (`s000`) mudavam a cada rodada. O primeiro artigo visto
    é estável mesmo quando um artigo mais antigo chega atrasado.
    """
    anchor = min(items, key=lambda a: (a.get("first_seen") or "",
                                        a.get("published") or "",
                                        a.get("link") or ""))
    link = anchor.get("link") or anchor.get("title", "")
    return "h" + hashlib.sha1(link.encode("utf-8")).hexdigest()[:8]


def assign_aliases(stories, previous):
    """Mantém `?story=` antigo funcionando: mapeia id anterior por sobreposição."""
    if not previous:
        return stories
    old = [(p.get("id"), {a.get("link") for a in p.get("articles", [])},
            set(p.get("aliases") or []))
           for p in previous if p.get("id")]
    for s in stories:
        links = {a.get("link") for a in s.get("articles", [])}
        best_j, best_id, best_old = 0.0, None, set()
        for oid, olinks, oaliases in old:
            if not links or not olinks:
                continue
            j = len(links & olinks) / len(links | olinks)
            if j > best_j:
                best_j, best_id, best_old = j, oid, oaliases
        aliases = set(s.get("aliases") or [])
        if best_id and best_j >= 0.40:
            aliases |= best_old  # herda aliases legados (ex.: s000)
            if best_id != s["id"]:
                aliases.add(best_id)
        if aliases:
            s["aliases"] = sorted(aliases)
    return stories


SOURCE_SUFFIX = re.compile(
    r"\s+[-–|]\s+(Folha de S\.Paulo|Folha|G1|O Globo|Estadão|UOL|CNN Brasil|"
    r"BBC Brasil|BBC News|The Guardian|New York Times|Valor Econômico|"
    r"Metrópoles|Poder360|Gazeta do Povo|InfoMoney|Veja|Exame|SBT News|"
    r"Band|Terra|R7|IstoÉ|CartaCapital|Brasil 247|Jovem Pan|Crusoé|"
    r"Nexo Jornal|Agência Pública|The Intercept Brasil|Repórter Brasil)\s*$",
    re.I)


def _clean_title(t: str | None) -> str:
    """F-05: remove sufixo de veículo e marcador de vídeo do título exibido."""
    t = (t or "").strip()
    t = SOURCE_SUFFIX.sub("", t).strip()
    t = re.sub(r"^\s*(VÍDEOS?|AO VIVO|ASSISTA)\s*:\s*", "", t, flags=re.I)
    t = re.sub(r"\s*\((vídeo|ao vivo|podcast|áudio)\)\s*$", "", t, flags=re.I)
    return t.strip() or (t or "")


def _representative(items, meta):
    """F-05: medoide (maior similaridade média com os demais títulos).

    O comprimento/factualidade (rep_score) só desempata. Assim a manchete é
    a mais central, não a mais longa ou a mais chamativa.
    """
    if len(items) <= 1:
        return items[0]
    X = tfidf_matrix([{"title": x.get("title", "")} for x in items])
    S = X @ X.T
    means = (S.sum(axis=1) - 1) / (len(items) - 1)
    scores = [rep_score(x, meta) for x in items]
    floor = max(scores) - 0.25
    cand = [i for i, sc in enumerate(scores) if sc >= floor]

    def _pub(i):
        for key in ("published", "first_seen"):
            v = items[i].get(key)
            if not v:
                continue
            try:
                return datetime.fromisoformat(v).timestamp()
            except ValueError:
                pass
        return 0.0

    # a manchete não pode ser uma versão antiga de uma história que segue
    # atualizada: entre a cobertura das últimas 24 h, pega a janela de 6 h do
    # artigo mais recente e escolhe o de melhor qualidade (rep_score); o
    # medoide só vale quando não há atualização.
    now = datetime.now(timezone.utc).timestamp()
    recent = [i for i in range(len(items))
              if _pub(i) and (now - _pub(i)) / 3600 <= 24]
    if recent:
        latest = max(_pub(i) for i in recent)
        window = [i for i in recent if latest - _pub(i) <= 6 * 3600]
        best = max(window, key=lambda i: (scores[i], float(means[i]), _pub(i)))
        return items[best]
    best = max(cand, key=lambda i: (float(means[i]), scores[i]))
    return items[best]


def build(sources, articles, llm_scores, thresh=0.38, use_embed=False):
    # rede de segurança: nenhum título de serviço/loteria entra na capa
    articles = [a for a in articles
                if not excluded_section(a.get("section"))
                and not excluded_title(a.get("title"))]
    groups = cluster(articles, thresh=thresh, use_embed=use_embed)
    meta = {s["id"]: s for s in sources}
    stories = []
    for g in groups:
        items = []
        for i in g:
            a = articles[i]
            llm = (llm_scores or {}).get(a["link"])
            if llm:  # apenas quando o usuário roda com --llm
                score, via = llm["score"], "llm"
            else:
                # posicionamento FIXO da publicação, sem análise por matéria
                score, via = round(float(a["base_bias"]), 2), "fonte"
            group = meta.get(a["source_id"], {}).get("group") or a["source_id"]
            src_meta = meta.get(a["source_id"], {})
            items.append({**a, "bias_score": round(score, 2), "via": via,
                          "bucket": bucket(score), "group": group,
                          "piece_kind": piece_kind(a, src_meta)})
        # A-3: opinião/longform aparecem no painel, mas não contam como cobertura
        coverage = [x for x in items if x["piece_kind"] in COVERAGE_KINDS]
        if len({x.get("group") or x["source_id"] for x in coverage}) < 2:
            continue
        items.sort(key=lambda x: x["bias_score"])
        by_b = {b: sum(1 for x in coverage if x["bucket"] == b)
                for b in BUCKETS}
        tot = len(coverage)
        gc, ind, avg = independent_counts(coverage, "bias_score")
        blind = blindspot_of5(gc["L"], gc["CL"], gc["C"], gc["CR"], gc["R"])
        # A-6: quem deu primeiro (um por veículo, por first_seen)
        def _pub(x):
            # "quem deu primeiro" = publicação; first_seen é só fallback
            return x.get("published") or x.get("first_seen") or ""
        by_source = {}
        for x in sorted(coverage, key=lambda y: (_pub(y), y.get("source_name", ""))):
            src = x.get("source_name") or x.get("source_id") or ""
            if src and src not in by_source:
                by_source[src] = x
        timeline = [{
            "source": x.get("source_name", ""),
            "title": x.get("title", ""),
            "link": x.get("link", ""),
            "published": _pub(x),
            "first_seen": x.get("first_seen") or _pub(x),
        } for x in sorted(by_source.values(),
                          key=lambda y: (_pub(y), y.get("source_name", "")))[:6]]
        # updated = última COBERTURA (opinião/vídeo não rejuvenesce a história)
        updated = max((_pub(x) for x in coverage), default="")
        if not updated:
            updated = max((_pub(x) for x in items), default="")
        rep = _representative(coverage, meta)
        rep_title = _clean_title(rep["title"])
        override = _service_headline([x.get("title", "") for x in coverage])
        if override:
            rep_title = override
        # resumo: prefere o do representante; senão o primeiro disponível
        summary = rep.get("summary") or next(
            (x["summary"] for x in coverage if x.get("summary")), "")
        stories.append({
            "id": _stable_id(items), "title": rep_title,
            "rep_link": rep.get("link", ""),
            "framing": framing_terms(coverage),
            "summary": summary[:300],
            "section": rep.get("section", ""),
            "section_label": section_label(rep.get("section")),
            "avg_bias": round(avg, 2),
            "recent": {"n_6h": _recent_groups(coverage, 6),
                       "n_24h": _recent_groups(coverage, 24)},
            "counts": {**by_b, "total": tot,
                       "independent": ind, "groups": gc,
                       "frames": len(items) - len(coverage),
                       "articles": len(items)},
            "pct": {b: (round(100 * gc[b] / ind) if ind else 0)
                    for b in BUCKETS},
            "blindspot": blind,
            "updated": updated,
            "timeline": timeline,
            "articles": [{
                "source": x["source_name"], "source_id": x["source_id"],
                "group": x.get("group") or x["source_id"],
                "piece_kind": x.get("piece_kind", "hard_news"),
                "first_seen": x.get("first_seen") or x.get("published", ""),
                "title": x["title"], "link": x["link"],
                "bias": x["bias_score"], "bucket": x["bucket"], "via": x["via"],
                "section": x.get("section", ""),
                "section_label": section_label(x.get("section")),
                "image": x.get("image", ""),
                "factuality": meta.get(x["source_id"], {}).get("factuality"),
                "ownership": meta.get(x["source_id"], {}).get("ownership"),
            } for x in items],
        })
    stories.sort(key=lambda s: s["counts"]["total"], reverse=True)
    return stories


def _check_payload(c, score, terms=()):
    if "label" not in c:  # defesa: checagem vinda de cache/ledger antigo
        from factcheck import verdict_label
        c = {**c, "label": verdict_label(c.get("verdict", "checagem"))}
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


def claim_match(a: set, b: set, idf: dict, df: Counter, floor: float = 0.34,
                a_text: str = "", b_text: str = "") -> float:
    """F4.2: mesma alegação, com precisão antes de recall.

    Além do score lexical, exige uma das duas evidências:
      - título quase idêntico (cobertura >= 0.80), ou
      - entidade multi-palavra específica em comum ("Auxílio Reconstrução").
    Sem isso, frases genéricas ("linha do tempo", "Lula") ligavam qualquer
    matéria a qualquer checagem (4/4 FPs medidos em 31/10).
    Medido nos 67 pares: P 1.00/R 0.67 com a guarda.
    """
    inter = a & b
    cov = _title_cov(a, b)
    strong_ent = False
    if a_text and b_text:
        shared = entities(a_text) & entities(b_text)
        strong_ent = any(" " in e and e not in ENTITY_GENERIC for e in shared)
    sc = claim_overlap(a, b, idf, df, floor)
    if sc:
        if (a_text and b_text) and not (strong_ent or cov >= 0.80):
            return 0.0
        return sc
    rare = any(df.get(w, 99) <= 4 for w in inter)
    if not (cov >= max(0.40, floor) and len(inter) >= 3 and rare):
        return 0.0
    if (a_text and b_text) and not strong_ent:
        return 0.0
    return cov


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
                  "ministro", "minister", "ministério", "ministry", "federal",
                  "deputado", "deputada", "senador", "senadora", "candidato",
                  "candidata", "governador", "governadora", "prefeito",
                  "prefeita", "vereador", "vereadora"}

ENTITY_ALIAS = {"brasil": "brazil", "eua": "us", "usa": "us",
                "estados unidos": "united states", "reino unido": "uk"}

# Pessoas não são âncora suficiente para agrupar eventos nem para o fallback
# de conceito (evita "Trump" juntar eleições de países diferentes).
PERSON_ENTITIES = {
    "lula", "bolsonaro", "jair bolsonaro", "flávio bolsonaro", "flávio",
    "trump", "donald trump", "milei", "netanyahu", "putin", "zelensky",
    "biden", "harris", "moraes", "alexandre de moraes", "mendonça",
    "nunes marques", "dino", "gilmar mendes", "barroso", "tarcísio",
    "zambelli", "malafaia", "vorcaro", "marco rubio", "rubio",
    "mauro vieira", "carney", "starmer", "bukele", "maduro",
}

# F3.4: âncoras BR→EN. Sem isso, "Ucrânia" e "Ukraine" eram entidades
# diferentes e o par "mísseis Patriot" (IN069) se perdia. Só nomes próprios
# de lugar/organização: traduzir "senado"→"senate" juntaria Congressos de
# países distintos.
ENTITY_TRANSLATE = {
    "ucrânia": "ukraine", "rússia": "russia", "alemanha": "germany",
    "frança": "france", "espanha": "spain", "itália": "italy",
    "japão": "japan", "irã": "iran", "coreia do norte": "north korea",
    "coreia do sul": "south korea", "união europeia": "european union",
    "otan": "nato", "onu": "un", "amazônia": "amazon", "méxico": "mexico",
    "canadá": "canada", "austrália": "australia",
    "áfrica do sul": "south africa", "nigéria": "nigeria", "índia": "india",
    "paquistão": "pakistan", "afeganistão": "afghanistan", "síria": "syria",
    "líbano": "lebanon", "iêmen": "yemen", "colômbia": "colombia",
    "bolívia": "bolivia", "equador": "ecuador", "egito": "egypt",
    "sudão": "sudan", "etiópia": "ethiopia", "somália": "somalia",
    "quênia": "kenya", "moçambique": "mozambique",
}


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
    norm = {ENTITY_TRANSLATE.get(w, w) for w in norm}
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


def _distinct_entities(ents: set) -> set:
    """Colapsa aliases: "Flávio Bolsonaro"/"Flávio"/"Bolsonaro" = 1 entidade."""
    multi = {e for e in ents if " " in e and e not in ENTITY_GENERIC}
    parts = {p for e in multi for p in e.split()}
    single = {e for e in ents
              if " " not in e and e not in ENTITY_GENERIC and e not in parts}
    return multi | single


# Não-jornalismo no pool longform: programas, quizzes, agendas, podcasts (F3.1)
NON_JOURNALISM = re.compile(
    r"assist[ai] ao programa|programa de \d|palavras cruzadas|\bquiz\b"
    r"|crossword|ao vivo agora|newsletter de|boletim de \d|edi[çc][ãa]o de hoje"
    r"|podcast completa|ouvinte|agenda do dia|hor[óo]scopo"
    r"|respostas? (enviad[ao]s?|da|de) (para )?(empresa|reportagem|redação)"
    r"|nota da redação|\berrata\b", re.I)

# Marcadores de análise (para F3.2: peça da mesma fonte só entra se for análise)
ANALYSIS_MARKERS = re.compile(
    r"an[áa]lise|por que|como \w+ (funciona|mudou|afeta)|entrevista"
    r"|conversa com|bastidores|longform|reportagem especial|perfil"
    r"|o que (isso|isso significa)|o futuro d[oe]|guia", re.I)


def _is_analysis(title: str) -> bool:
    return bool(ANALYSIS_MARKERS.search(title or ""))


# A-3: só estas peças contam como cobertura para barra/blindspot
COVERAGE_KINDS = {"hard_news", "analysis", "explainer"}
URL_KIND = (
    # Foro de Teresina: /web/ftNNN/ com imagem foro_news_*, sem autor/dek
    (r"piaui\.uol\.com\.br/web/ft\d", "podcast"),
    (r"/(podcast|podcasts|audio)/", "podcast"),
    (r"/(video|videos|v[ií]deos)/", "video"),
    (r"/(ao-vivo|live)/", "live"),
    (r"/(fato-ou-fake|checagem|verificacao)/", "fact_check"),
    (r"/(opiniao|opini[aã]o|colunas?|blogs?|editorial|artigos?)/", "opinion"),
    (r"/analise/", "analysis"),
    (r"/entrevista/", "interview"),
)


def _is_non_text_url(url: str | None) -> bool:
    """URL de peça não-textual (podcast/vídeo/live) pelos padrões de URL."""
    u = (url or "").lower()
    for rx, kind in URL_KIND:
        if kind in ("podcast", "video", "live") and re.search(rx, u):
            return True
    return False


def piece_kind(item: dict, source: dict | None = None) -> str:
    """Classifica a peça por URL, título, editoria e padrão da fonte (A-3).

    Ordem: URL (mais específica), editoria, título, `longform` da fonte,
    default hard_news. Opinião/longform não contam na barra; podcasts/vídeos/
    ao vivo não entram no "Aprofunde-se".
    """
    url = (item.get("link") or "").lower()
    for rx, kind in URL_KIND:
        if re.search(rx, url):
            return kind
    title = item.get("title") or ""
    sec = _norm_sec(item.get("section"))
    if sec in {"podcast", "podcasts", "audio"}:
        return "podcast"
    if sec in {"video", "videos"}:
        return "video"
    if sec in {"ao-vivo", "live"}:
        return "live"
    if re.search(r"\bao\s+vivo\b", title, re.I):
        return "live"
    if re.search(r"^\s*v[ií]deos?\s*:|\(v[ií]deo\)|\bassista\b", title, re.I):
        return "video"
    if re.search(r"\bpodcast\b|\b[áa]udio\b", title, re.I):
        return "podcast"
    if re.search(r"\bopini[aã]o\b", title, re.I):
        return "opinion"
    if re.search(r"\bentrevista\b", title, re.I):
        return "interview"
    if re.search(r"\ban[áa]lise\b", title, re.I) or ANALYSIS_MARKERS.search(title):
        return "analysis"
    if re.search(r"\b(entenda|explica|guia|como funciona|o que (é|significa))\b",
                 title, re.I) or re.search(r"\bpor que\b", title, re.I):
        return "explainer"
    if sec in LONGFORM_SECTIONS:
        return "opinion"
    if source and source.get("longform"):
        return "longform"
    return "hard_news"


def _story_entities(s) -> set:
    """Entidades de todas as manchetes da história (recall maior que só a representante)."""
    out: set = set()
    for a in s.get("articles", []):
        out |= entities(a.get("title", ""))
    return out


HOLIDAY_SERVICE = re.compile(
    r"\b(abre e fecha|o que abre|o que fecha|hor[aá]rios de [oô]nibus"
    r"|mudan[cç]as no tr[aâ]nsito|funcionamento)\b", re.I)


def _service_headline(titles) -> str | None:
    """Manchete genérica quando o grupo é serviço de feriado em várias cidades.

    Sem isso, o representante vira a versão de uma cidade ("Finados em Manaus")
    e parece que a história é local, quando é um serviço nacional.
    """
    ts = [x for x in titles if x]
    if len(ts) < 2:
        return None
    hits = sum(1 for x in ts if HOLIDAY_SERVICE.search(x))
    if hits < max(2, len(ts) // 2):
        return None
    low = " ".join(ts).lower()
    if "finados" in low:
        return ("Funcionamento e horários no feriado de Finados "
                "nas capitais do Brasil")
    return None


def _recent_groups(coverage, hours, now=None) -> int:
    """Grupos independentes com cobertura dentro da janela (p/ ranking 6 h)."""
    now = now or datetime.now(timezone.utc).timestamp()
    groups = set()
    for x in coverage:
        ts = x.get("published") or x.get("first_seen")
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            t = float(x.get("ts") or 0)
        if now - t <= hours * 3600:
            groups.add(x.get("group") or x.get("source_id"))
    return len(groups)


def _recompute(s) -> dict:
    """Recalcula contagens, média e blindspot a partir das matérias da história."""
    arts = s.get("articles", [])
    coverage = [x for x in arts
                if not x.get("piece_kind") or x["piece_kind"] in COVERAGE_KINDS]
    by_b = {b: sum(1 for x in coverage if x.get("bucket") == b)
            for b in BUCKETS}
    gc, ind, avg = independent_counts(coverage, "bias")
    s["counts"] = {**by_b, "total": len(coverage),
                   "independent": ind, "groups": gc,
                   "frames": len(arts) - len(coverage),
                   "articles": len(arts)}
    s["pct"] = {b: (round(100 * gc[b] / ind) if ind else 0) for b in BUCKETS}
    s["avg_bias"] = round(avg, 2)
    s["recent"] = {"n_6h": _recent_groups(coverage, 6),
                   "n_24h": _recent_groups(coverage, 24)}
    s["blindspot"] = blindspot_of5(*[gc[b] for b in BUCKETS])
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
# Lugar é "onde", não "sobre": um estado/cidade junta pautas sem relação
# ("Mato Grosso" = violência em MS + soja + TCE). Países seguem valendo
# (guerra, eleição), então a lista é subnacional de propósito.
HUB_STOP_GEO = {
    "acre", "alagoas", "amapá", "amapa", "amazonas", "bahia", "ceará", "ceara",
    "distrito federal", "espírito santo", "espirito santo", "goiás", "goias",
    "maranhão", "maranhao", "mato grosso", "mato grosso do sul", "minas gerais",
    "pará", "para", "paraíba", "paraiba", "paraná", "parana", "pernambuco",
    "piauí", "piaui", "rio de janeiro", "rio grande do norte",
    "rio grande do sul", "rondônia", "rondonia", "roraima", "santa catarina",
    "são paulo", "sao paulo", "sergipe", "tocantins", "brasília", "brasilia",
    # capitais e cidades grandes (as multi-palavra são as que viram chave)
    "belo horizonte", "porto alegre", "foz do iguaçu", "foz do iguacu",
    "são josé dos campos", "sao josé dos campos", "são bernardo do campo",
    "santo andré", "santo andre", "juiz de fora", "campos dos goytacazes",
    "feira de santana", "montes claros", "ribeirão preto", "ribeirao preto",
    "são josé do rio preto", "sao josé do rio preto", "joinville", "londrina",
    "maringá", "maringa", "uberlândia", "uberlandia", "cuiabá", "cuiaba",
    "campo grande", "são luís", "sao luis", "belém", "belem", "manaus",
    "macapá", "macapa", "porto velho", "boa vista", "rio branco", "palmas",
    "teresina", "fortaleza", "natal", "joão pessoa", "joao pessoa", "maceió",
    "maceio", "aracaju", "salvador", "vitória", "vitoria", "florianópolis",
    "florianopolis", "curitiba", "goiânia", "goiania", "campinas", "santos",
    "niterói", "niteroi", "duque de caxias", "nova iguaçu", "nova iguacu",
}

HUB_STOP = ENTITY_GENERIC | HUB_STOP_GEO | {
    "estados unidos", "reino unido", "america latina",
    "américa latina", "oriente médio", "oriente medio", "união europeia",
}
HUB_ACRONYMS = {"stf", "tse", "pf", "pgr", "cnj", "tcu", "bndes", "ibge", "copom",
                "g20", "brics", "onu", "otan", "pt", "pl", "psdb", "ptb", "pcdob"}


def _hub_label(key: str) -> str:
    parts = [w.upper() if w in HUB_ACRONYMS else w[:1].upper() + w[1:]
             for w in key.split()]
    return " ".join(parts)


def _supports_entity(title_ents: set, key: str) -> bool:
    """O título trata do nome? Aceita só o prenome como alias.

    "Flávio" sozinho representa "Flávio Bolsonaro"; "Bolsonaro" sozinho é o
    Jair (ou a família), então não vale como apoio.
    """
    if key in title_ents:
        return True
    first = key.split()[0]
    return len(first) >= 4 and first not in ENTITY_GENERIC and first in title_ents


def attach_hubs(stories, min_stories=3, window_h=72.0):
    """F2: marca cada história com a "pauta" (narrativa) a que pertence.

    Só nomes próprios multi-palavra servem de chave (nunca "lula" ou "senado"):
    genéricos agruparia pautas sem relação. Não altera contagens — a história
    continua sendo o fato; a pauta é só navegação entre ângulos.

    A entidade precisa ser **assunto** da história, não menção lateral: tem de
    estar na manchete e em pelo menos 2 títulos. Sem isso, "Democratas cobram
    que Trump reconheça vitória de Lula" entrava na pauta "Flávio Bolsonaro"
    por causa de uma citação solta.
    """
    ts = [_ts_of(s) for s in stories]
    per_title = [[_title_entities(a.get("title", "")) for a in s.get("articles", [])]
                 for s in stories]

    def support(i: int, key: str) -> int:
        return sum(1 for e in per_title[i] if _supports_entity(e, key))

    index: dict[str, list[int]] = {}
    for i, s in enumerate(stories):
        rep = _title_entities(s.get("title", ""))
        keys = {k for e in per_title[i] for k in e
                if " " in k and k not in HUB_STOP}
        for k in keys:
            if not _supports_entity(rep, k):
                continue
            need = min(2, len(per_title[i]))  # história de 1 matéria basta a manchete
            if support(i, k) < need:
                continue
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


# Ganho medido em 31/10/2026 sobre 60 pares rotulados de aprofundamento:
# entidade OR embedding >= 0.75 → P 0.94→0.95, R 0.62→0.69 (0 falso positivo
# novo). Só vale com --embed; o CI roda a regra lexical.
#
# CUIDADO (viés de seleção): a amostra já passava pelo pré-filtro lexical.
# Aplicar o embedding a TODOS os pares abre conexões sem nenhuma âncora
# ("diplomata argentina" × "voto das capitais"), então ele só confirma pares
# com entidade em comum ou cobertura de título >= EMB_PREFILTER_COV.
EMB_BOOST = 0.75
# C-3 híbrido (decisão 01/11/2026): limiares do eval em 120 pares
# (same P 0.80/R 0.75, rel P 0.88/R 0.71; top-3 idêntico à regra).
EMB_SAME_TH = 0.55
EMB_REL_TH = 0.45


def longform_emb_score(ent, rec, emb_cos, cov, quality=1.0):
    """Scorer híbrido do eval (modo emb), mesma fórmula calibrada."""
    return (0.45 * emb_cos + 0.30 * ent + 0.10 * rec
            + 0.10 * quality + 0.05 * cov)
EMB_PREFILTER_COV = 0.12


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


LEITURAS_AD = re.compile(
    r"\bpubli\b|patrocinad|publicidade|conte[uú]do de marca|"
    r"informe publicit[aá]rio|conte[uú]do patrocinado", re.I)


def _piaui_featured(timeout: int = 20):
    """Primeira matéria em destaque na home da piauí (classe 'destaque')."""
    import requests
    try:
        r = requests.get("https://piaui.folha.uol.com.br/", timeout=timeout,
                         headers={"User-Agent": "Balanco/0.2 (+news aggregator; local)"})
        sec = re.search(r'<section[^>]*class="[^"]*destaque1a[^"]*"[^>]*>'
                        r'(.*?)</section>', r.text, re.S | re.I)
        block = sec.group(1) if sec else r.text
        m = re.search(r'<a href="(/revista/[^"]+)"', block)
        if not m:
            return None
        link = "https://piaui.uol.com.br" + m.group(1)
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", block, re.S)
        dek = re.search(r'linha-fina-grande[^>]*>(.*?)</p>', block, re.S)
        clean = lambda s: _clean_text(html.unescape(re.sub(r"<[^>]+>", " ", s)))
        title = clean(h1.group(1)) if h1 else ""
        summary = clean(dek.group(1)) if dek else ""
        img = re.search(r'<img[^>]+src="([^"]+)"', block)
        image = img.group(1) if img else ""
        if image.startswith("/"):
            image = "https://piaui.uol.com.br" + image
        if not title:
            return None
        return {"title": title, "link": link, "summary": summary,
                "image": image}
    except Exception:
        return None


def _closed(store, x: dict) -> bool:
    """Fechado para leitura? A piauí é isenta (a assinatura é o modelo)."""
    if x.get("source_id") == "piaui":
        return False
    return _is_paywalled(store, x.get("link", ""))


def _is_paywalled(store, link: str) -> bool:
    get_body = getattr(store, "get_body", None)
    if get_body is None:
        return False
    hit = get_body(link)
    if hit is None:
        try:
            from enrich import fetch_body
            hit = fetch_body(link, store)
        except Exception:
            return False
    return bool((hit or {}).get("paywalled"))


def build_leituras(store, sources, days=10, limit=8, exclude_links=None,
                   stories=None):
    """C-1: índice de longform dos últimos N dias, independente das histórias.

    A janela de 120 dias do cache é a fonte; a seleção limita 2 peças por
    fonte e exclui não-jornalismo/resumo vazio. Não tenta casar com história
    (isso é C-3); serve à seção "Leituras da semana".
    """
    if store is None:
        return []
    exclude = set(exclude_links or [])
    seen = set()
    out = []
    for s in sources:
        if not s.get("longform"):
            continue
        for a in store.recent(s["id"], window_h=days * 24, limit=200):
            title = a.get("title", "")
            if not title or NON_JOURNALISM.search(title):
                continue
            if LEITURAS_AD.search(title):
                continue  # publi/informe do próprio site não é leitura
            if piece_kind(a, s) in ("podcast", "video", "live"):
                continue  # F-08: Foro de Teresina & cia não são leitura
            if excluded_section(a.get("section")) or excluded_title(title):
                continue
            summary = _clean_text(a.get("summary"))
            if summary.lower() in ("", "none", "null"):
                continue
            if a["link"] in exclude or a["link"] in seen:
                continue
            seen.add(a["link"])
            out.append({
                "source_id": s["id"], "source": s["name"],
                "title": title, "link": a["link"],
                "published": a["published"], "summary": summary[:240],
                "image": a.get("image", ""), "bias": float(s.get("bias", 0)),
            })
    out.sort(key=lambda x: x["published"], reverse=True)
    # destaque real da home da piauí (pode não estar no RSS)
    feat = _piaui_featured()
    if feat and feat["link"] not in {x["link"] for x in out}:
        out.insert(0, {"source_id": "piaui", "source": "Revista piauí",
                       "title": feat["title"], "link": feat["link"],
                       "published": datetime.now(timezone.utc).isoformat(),
                       "summary": (feat.get("summary") or "")[:240],
                       "image": feat.get("image", ""), "bias": -0.8,
                       "featured": True})
    elif feat:
        for x in out:
            if x["link"] == feat["link"]:
                x["featured"] = True

    picked, per = [], Counter()
    for x in out:
        if per[x["source_id"]] >= 2:
            continue
        picked.append(x)
        per[x["source_id"]] += 1
        if len(picked) >= limit:
            break

    # remove fechados (muro), exceto o destaque da piauí, e repõe do pool
    verified, seen = [], {x["link"] for x in picked}
    for x in picked:
        if x.get("featured") or not _closed(store, x):
            verified.append(x)
    if len(verified) < limit:
        for x in out:
            if x["link"] in seen:
                continue
            if _closed(store, x):
                continue
            verified.append(x)
            seen.add(x["link"])
            if len(verified) >= limit:
                break
    picked = verified

    # 8) piauí: sempre 2 leituras — a mais recente (destaque da home) e a mais
    # relacionada aos temas da semana. Se faltar, entra no lugar da última
    # peça não-piauí (respeitando o limite).
    have = [x for x in picked if x["source_id"] == "piaui"]
    if len(have) < 2:
        cand = [x for x in out if x["source_id"] == "piaui"
                and x["link"] not in {p["link"] for p in picked}]
        ents = set()
        for s in (stories or []):
            ents |= entities(s.get("title", ""))
        for x in cand:
            x["_rel"] = len(entities(x.get("title", "") + " " +
                                     (x.get("summary") or "")) & ents)
        add = []
        # 1ª vaga: o destaque real da home (se ainda não estiver na lista)
        feat = next((x for x in out if x["source_id"] == "piaui"
                     and x.get("featured")), None)
        if feat is not None and feat["link"] not in {
                p["link"] for p in picked}:
            add.append(feat)
        # 2ª vaga: a mais relacionada aos temas da semana (não fechada)
        rest = [x for x in cand if x["link"] not in {a["link"] for a in add}
                and not _closed(store, x)]
        if rest:
            add.append(max(rest, key=lambda x: (x["_rel"], x["published"])))
        for x in add[:2 - len(have)]:
            picked.append(x)
        while len(picked) > limit:
            drop = next((i for i in range(len(picked) - 1, -1, -1)
                         if picked[i]["source_id"] != "piaui"), None)
            if drop is None:
                break
            picked.pop(drop)
        for x in picked:
            x.pop("_rel", None)
        picked.sort(key=lambda x: x["published"], reverse=True)
    return picked


def attach_longreads(stories, articles, longform_ids, per_story=3, use_embed=False):
    """Liga cada história a longform (piauí & cia) em duas relações (C-2).

    - "same" (até 14 dias): mesmo fato; mantém a regra de entidade atual.
    - "background" (15–120 dias): pano de fundo; exige 2+ entidades
      específicas distintas e cobertura de título >= 0,20, para não repetir
      o flood de "Flávio" medido com 120 dias.
    Não afirma nada sobre o artigo: só sugere leitura, com link.
    """
    pool = []
    for a in articles:
        if a.get("source_id") in longform_ids:
            if NON_JOURNALISM.search(a.get("title", "")):
                continue  # F3.1: programa/quiz/agenda não é aprofundamento
            if _is_non_text_url(a.get("link")):
                continue  # F-08: Foro de Teresina & cia não é aprofundamento
            pool.append((entities(a.get("title", "")),
                         entities(a.get("title", "") + " " + (a.get("summary") or "")),
                         a))
    X, n_st = None, len(stories)
    idf = None
    if use_embed and pool:
        try:
            X = embed_matrix([{"title": s.get("title", "")} for s in stories] +
                             [{"title": a.get("title", "")} for _, _, a in pool])
            idf, _ = build_idf(
                [set(tok(s.get("title", ""))) for s in stories] +
                [set(tok(a.get("title", ""))) for _, _, a in pool])
        except Exception as e:
            X = None
            print(f"  [aviso] embeddings indisponíveis no aprofundamento ({e})")
    now = datetime.now(timezone.utc).timestamp()
    for si, s in enumerate(stories):
        s["longreads"] = []
        se = entities(s.get("title", ""))
        if not se:
            continue
        st = set(tok(s.get("title", "")))
        covered = {a.get("source") or a.get("source_name") for a in s.get("articles", [])}
        cands = []
        for pi, (le_title, le_full, a) in enumerate(pool):
            link = a.get("link", "")
            if not link:
                continue
            try:
                ts = float(a.get("ts")) if a.get("ts") else now
            except (TypeError, ValueError):
                ts = now
            age_days = max(0.0, (now - ts) / 86400)
            if age_days > 120:
                continue
            relation = "same" if age_days <= 14 else "background"
            le = le_title if relation == "same" else le_full
            ok, terms = entity_match(se, le)
            emb_score = None
            if X is not None:
                emb_cos = float(X[si] @ X[n_st + pi])
                pe = entities(a.get("title", "") + " " + (a.get("summary") or ""))
                den = sum(idf.get(e, 1) for e in pe) or 1
                ent = sum(idf.get(e, 1)
                          for e in _distinct_entities(se & pe)) / den
                rec = math.exp(-age_days / 60.0)
                cov = _title_cov(st, set(tok(a.get("title", ""))))
                emb_score = longform_emb_score(ent, rec, emb_cos, cov)
            if not ok and emb_score is not None:
                # C-3 híbrido: âncora lexical obrigatória (decisão 01/11/2026),
                # admissão pelo scorer calibrado no eval.
                lex_ok = _title_cov(st, set(tok(a.get("title", "")))) >= EMB_PREFILTER_COV
                thr = EMB_SAME_TH if relation == "same" else EMB_REL_TH
                if lex_ok and emb_score >= thr:
                    ok = True
                    terms = sorted((se & pe) - ENTITY_GENERIC)[:6]
            if not ok:
                continue
            shared = se & le
            distinct = _distinct_entities(shared)
            cov = _title_cov(st, set(tok(a.get("title", ""))))
            if relation == "same" and age_days > 3 and len(distinct) < 2:
                continue
            if relation == "background" and (len(distinct) < 2 or cov < 0.30):
                continue
            # F3.2: se a fonte já cobre a história, só peça de análise entra
            if a.get("source_name") in covered and not _is_analysis(a.get("title", "")):
                continue
            why = sorted(shared | (se & entities(a.get("summary") or "")))[:4]
            if emb_score is not None:
                score = (round(emb_score, 4), len(distinct),
                         round(cov, 3), len(terms))
            else:
                score = (1 if relation == "same" else 0, len(distinct),
                         round(cov, 3), len(terms))
            cands.append((score, link, a, relation, age_days, why))
        # C-4: cota de linha editorial — no máx. 2 peças do mesmo lado
        # (sinal do base_bias) por história; com 3 vagas, garante ao menos
        # 2 linhas distintas. Neutra entre fontes (sem bônus para a piauí).
        def _side(a):
            try:
                b = float(a.get("base_bias", 0.0))
            except (TypeError, ValueError):
                b = 0.0
            return "L" if b <= -0.3 else ("R" if b >= 0.3 else "C")
        seen, out, used_src, used_side = set(), [], set(), Counter()
        for _, link, a, relation, age_days, why in sorted(cands, reverse=True):
            if link in seen or a.get("source_name") in used_src:
                continue  # F3.3: no máx. 1 peça por fonte por história
            if used_side[_side(a)] >= 2:
                continue  # C-4: cota de linha editorial
            seen.add(link)
            used_src.add(a.get("source_name"))
            used_side[_side(a)] += 1
            out.append({
                "source": a.get("source_name", ""),
                "title": a.get("title", ""),
                "link": link,
                "terms": why,
                "relation": relation,
                "age_days": round(age_days, 1),
                "why": ", ".join(why[:3]),
                "kind": a.get("piece_kind") or "longform",
            })
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


NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def numbers(text: str | None) -> set[float]:
    """Números do evento (6,3 / 6.3 / 500), ignorando anos e valores triviais."""
    out = set()
    for m in NUM_RE.findall(text or ""):
        try:
            v = float(m.replace(",", "."))
        except ValueError:
            continue
        if v < 2:
            continue
        if 1900 <= v <= 2100 and v == int(v):
            continue
        out.add(round(v, 2))
    return out


def _numbers_match(a: set, b: set) -> bool:
    return any(abs(x - y) / max(abs(x), abs(y), 1) <= 0.05
               for x in a for y in b)


# B-3: conceitos recorrentes sem nome próprio (PT/EN)
CONCEPT = {
    "hack": "cyber", "hacker": "cyber", "hackers": "cyber",
    "hacking": "cyber", "ciberataque": "cyber", "cyberattack": "cyber",
    "tarifa": "tariff", "tarifas": "tariff", "tarifaço": "tariff",
    "tariff": "tariff", "tariffs": "tariff",
    "eleição": "election", "eleições": "election", "election": "election",
    "elections": "election", "voto": "election", "vote": "election",
    "voters": "election", "mandato": "election", "mandatos": "election",
    "win": "election", "wins": "election", "victory": "election",
    "vitória": "election", "vitórias": "election", "derrota": "election",
    "defeat": "election", "juros": "rates", "interest": "rates",
    "selic": "rates", "protesto": "protest", "protestos": "protest",
    "protest": "protest", "protests": "protest", "seca": "drought",
    "drought": "drought", "enchente": "flood", "flood": "flood",
    "flooding": "flood", "míssil": "missile", "mísseis": "missile",
    "missile": "missile", "missiles": "missile", "ebola": "ebola",
}


def concepts(text: str | None) -> set[str]:
    return {CONCEPT[x] for x in tok(text or "") if x in CONCEPT}


def _world_match(se: set, intl_title: str, summary: str = "",
                 story_title: str = "") -> tuple[bool, list]:
    """Casa história BR com peça internacional. Título primeiro; o resumo só
    entra se trouxer uma entidade multi-palavra específica.

    Medido em 31/10/2026 (40 pares rotulados): título + tradução de âncoras
    dá P 1.00/R 0.82; o resumo com essa guarda sobe para R 0.91 sem FP.
    Resumo sozinho (entidade ampla) abriria "Trump" × qualquer pauta.
    """
    ok, terms = entity_match(se, entities(intl_title))
    if ok:
        return True, terms
    if summary:
        ok, terms = entity_match(se, entities(intl_title + " " + summary))
        if ok and any(" " in t and t not in ENTITY_GENERIC for t in terms):
            return True, terms
    # evento com número forte: "Binance" + US$ 6,3 bi × "$6.3 Billion"
    if story_title:
        text = intl_title + " " + summary
        shared = {e for e in se & entities(text) if e not in ENTITY_GENERIC}
        if not shared:
            return False, []
        strong = shared - PERSON_ENTITIES
        if _numbers_match(numbers(story_title), numbers(text)):
            return True, sorted(shared)[:6]
        if strong and (concepts(story_title) & concepts(text)):
            return True, sorted(strong)[:6]
    return False, []


def group_intl_articles(articles):
    """B-2: agrupa peças internacionais pelo mesmo evento.

    Combina o cluster TF-IDF (duplicatas de título) com uma regra forte de
    entidade + número (ex.: "Binance" + US$ 6,3 bi), que o TF-IDF sozinho
    não pega quando a redação muda.
    """
    if not articles:
        return []
    now = datetime.now(timezone.utc).timestamp()
    for a in articles:
        a.setdefault("ts", now)
        a.setdefault("section", "")
        a.setdefault("source_id", a.get("source", "?"))
    groups = cluster(articles, thresh=0.38, window_h=72)
    gents, gnums = [], []
    for g in groups:
        e, n = set(), set()
        for i in g:
            a = articles[i]
            text = (a.get("title", "") + " " + (a.get("summary") or ""))
            e |= entities(text)
            n |= numbers(text)
        gents.append(e)
        gnums.append(n)
    parent = list(range(len(groups)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            shared = {e for e in gents[i] & gents[j] if e not in ENTITY_GENERIC}
            shared_strong = shared - PERSON_ENTITIES
            if shared_strong and _numbers_match(gnums[i], gnums[j]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    merged = {}
    for gi, g in enumerate(groups):
        merged.setdefault(find(gi), []).extend(g)
    out = [[articles[i] for i in idxs] for idxs in merged.values()]
    out.sort(key=lambda g: (-len(g), -max(a.get("ts", 0) for a in g)))
    return out


# Entidades que marcam "sobre o Brasil" (B-4: Brasil visto de fora)
BR_ENTS = {"brasil", "brazil", "brasília", "brasilia", "lula", "bolsonaro"}


def attach_world(stories, intl_articles, per_story=3, use_embed=False,
                 source_meta=None):
    """B-2/B-3: liga histórias a grupos internacionais (evento, não peça).

    Cada grupo mostra uma peça representante, o número de veículos e as
    fontes; a mesma peça nunca aparece em duas histórias.
    """
    groups = group_intl_articles(intl_articles)
    source_meta = source_meta or {}
    pool = []
    for g in groups:
        rep = _representative(g, source_meta)
        rep_title = _clean_title(rep.get("title", ""))
        group_summary = " ".join(
            (a.get("title", "") + " " + (a.get("summary") or ""))
            for a in g)[:1600]
        seen_link, sources = set(), []
        for a in g:
            src = a.get("source_name", "")
            link = a.get("link", "")
            if not src or not link or link in seen_link:
                continue
            seen_link.add(link)
            sources.append({"source": src, "title": a.get("title", ""),
                            "link": link})
        pool.append((rep_title, group_summary, rep, g, sources))
    X, n_st = None, len(stories)
    if use_embed and pool:
        try:
            X = embed_matrix([{"title": s.get("title", "")} for s in stories] +
                             [{"title": it} for it, _, _, _, _ in pool])
        except Exception as e:
            print(f"  [aviso] embeddings indisponíveis no 'Lá fora' ({e})")
    for si, s in enumerate(stories):
        s["world"] = []
        story_text = s.get("title", "")
        se = entities(story_text)
        if not se:
            continue
        st = set(tok(story_text))
        cands = []
        for pi, (it, isum, rep, g, sources) in enumerate(pool):
            if not it:
                continue
            ok, terms = _world_match(se, it, isum, story_text)
            if not ok and X is not None:
                lex_ok = _title_cov(st, set(tok(it))) >= EMB_PREFILTER_COV
                if lex_ok and float(X[si] @ X[n_st + pi]) >= EMB_BOOST:
                    ok = True
            if ok:
                n_src = len({a.get("source_name") for a in g
                             if a.get("source_name")})
                cands.append((len(terms), rep.get("link", ""), rep, g,
                              sources, n_src, terms))
        seen, out = set(), []
        for _, link, rep, g, sources, n_src, terms in sorted(cands, reverse=True):
            if not link or link in seen:
                continue
            seen.add(link)
            meta = source_meta.get(rep.get("source_id") or "", {}) or {}
            out.append({
                "source": rep.get("source_name", ""),
                "title": _clean_title(rep.get("title", "")),
                "link": link,
                "terms": terms,
                "n_sources": n_src,
                "sources": sources[:6],
                "country": meta.get("country", ""),
                "bloc": meta.get("bloc", ""),
                "lang": meta.get("lang", ""),
            })
            if len(out) >= per_story:
                break
        s["world"] = out
    # uma peça/grupo só na história de maior correspondência
    best = {}
    for s in stories:
        total = (s.get("counts") or {}).get("total", 0)
        for w in s.get("world", []):
            score = len(w.get("terms") or [])
            cand = (total, score, id(s))
            if w["link"] not in best or cand[:2] > best[w["link"]][:2]:
                best[w["link"]] = cand
    for s in stories:
        s["world"] = [w for w in s.get("world", [])
                      if best.get(w["link"], (0, 0, None))[2] == id(s)]
    # B-4: grupos sem história BR → "só lá fora" (≥3 países) e
    # "Brasil visto de fora" (mencionam o Brasil)
    attached = {w["link"] for s in stories for w in s.get("world", [])}
    only_world, brasil_abroad, seen_g = [], [], set()
    for rep_title, group_summary, rep, g, sources in pool:
        link = rep.get("link", "")
        key = link or rep_title
        if not key or key in seen_g or link in attached:
            continue
        seen_g.add(key)
        n_src = len({a.get("source_name") for a in g if a.get("source_name")})
        countries = sorted({
            (source_meta.get(a.get("source_id") or "", {}) or {}).get("country", "")
            for a in g if a.get("source_id")} - {""})
        gents = entities(rep_title + " " + group_summary[:800])
        meta = source_meta.get(rep.get("source_id") or "", {}) or {}
        entry = {
            "source": rep.get("source_name", ""),
            "title": _clean_title(rep.get("title", "")),
            "link": link,
            "n_sources": n_src,
            "countries": countries,
            "sources": sources[:6],
            "country": meta.get("country", ""),
            "bloc": meta.get("bloc", ""),
            "lang": meta.get("lang", ""),
        }
        if gents & BR_ENTS:
            brasil_abroad.append((n_src, entry))
        elif len(countries) >= 3:
            only_world.append((n_src, entry))
    only_world = [e for _, e in sorted(only_world, key=lambda t: t[0],
                                              reverse=True)[:8]]
    brasil_abroad = [e for _, e in sorted(brasil_abroad, key=lambda t: t[0],
                                          reverse=True)[:8]]
    return stories, {"only_world": only_world, "brasil_abroad": brasil_abroad}

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

    c_titles = [c["title"] for c in checks]

    def match(a, b, floor, at="", bt=""):
        return claim_match(a, b, idf, df, floor, at, bt)

    def terms(a, b):
        return sorted(a & b)[:6]

    # nível história
    for si, s in enumerate(stories):
        cands = []
        for ci, c in enumerate(checks):
            sc = match(s_sets[si], c_sets[ci], story_min,
                       s["title"], c_titles[ci])
            if sc:
                cands.append((sc, ci))
        cands.sort(reverse=True)
        s["checks"] = [_check_payload(checks[ci], sc, terms(s_sets[si], c_sets[ci]))
                       for sc, ci in cands[:2]]

    # nível matéria + histórico por fonte
    ledger = {}
    matches = []
    for k, (si, ai) in enumerate(a_ref):
        a_title = stories[si]["articles"][ai]["title"]
        cands = [(match(a_sets[k], c_sets[ci], article_min,
                        a_title, c_titles[ci]), ci)
                 for ci in range(len(checks))]
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
                    help="usa embeddings nas conexões (longform/internacional); ONNX/fastembed, fallback lexical")
    ap.add_argument("--embed-cluster", action="store_true",
                    help="usa embeddings também no agrupamento (experimental; requer cooperação A-4)")
    ap.add_argument("--pair-model", default=os.environ.get("PAIR_MODEL"),
                    help="gate de par (JSON): veta fusões com P(same) abaixo do limiar")
    ap.add_argument("--no-checks", action="store_true",
                    help="não coleta checagens do G1 Fato ou Fake / Lupa")
    ap.add_argument("--body", action="store_true",
                    help="enriquece matérias (meta + corpo público, com cache; ignora robots de editoria)")
    ap.add_argument("--body-cap", type=int, default=120,
                    help="máximo de páginas buscadas por rodada com --body "
                         "(paralelo por host)")
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
        sitemap_ids = {s["id"] for s in sources
                       if s.get("fetcher") == "sitemap"}
        estats = enrich_articles(articles, store, cap=args.body_cap,
                                 priority_sources=sitemap_ids)
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

    if args.pair_model:
        try:
            m = load_pair_model(args.pair_model)
            print(f"[3/4] gate de par ativo: {args.pair_model} "
                  f"(veto < {m.get('veto_threshold', 0.25)})")
        except Exception as ex:
            print(f"  [aviso] gate de par indisponível ({ex}); seguindo sem ele")
    print("[3/4] agrupando stories...")
    news = [a for a in articles if a.get("kind", "br") != "intl"]
    intl = [a for a in articles if a.get("kind") == "intl"]
    print(f"  {len(news)} nacionais + {len(intl)} internacionais (fora das barras)")
    stories = build(sources, news, llm_scores, thresh=args.thresh,
                    use_embed=args.embed_cluster)
    n_before = len(stories)
    stories = consolidate(stories, use_embed=args.embed)
    stories = attach_hubs(stories)
    source_meta = {s["id"]: s for s in sources}
    front_stats = {}
    stories, front_only, pautas = attach_front_pages(
        stories, source_meta=source_meta, stats=front_stats)
    print(f"[3b/4] capas: " + ", ".join(
        f"{k} {v}" for k, v in front_stats.items()) +
        f"; {sum(front_stats.values())} manchetes, {len(front_only)} pauta(s) fora do feed")
    n_hub = len({s["hub"]["key"] for s in stories if s.get("hub")})
    print(f"[3a/4] {n_before} grupos → {len(stories)} histórias consolidadas "
          f"({n_before - len(stories)} fusões de mesmo fato), {n_hub} pautas")

    longform_ids = {s["id"] for s in sources if s.get("longform")}
    # C-1/C-2: índice de 120 dias independente da janela de 72 h das notícias
    longform_extra = []
    if store is not None:
        from store import PER_SOURCE_CAP
        seen_links = {a.get("link") for a in articles}
        for src in sources:
            if src["id"] not in longform_ids:
                continue
            for a in store.recent(src["id"], window_h=120 * 24,
                                  limit=PER_SOURCE_CAP):
                if not a.get("link") or a["link"] in seen_links:
                    continue
                if NON_JOURNALISM.search(a.get("title", "")):
                    continue
                if excluded_section(a.get("section")) or excluded_title(a.get("title")):
                    continue
                a.update(source_id=src["id"], source_name=src["name"],
                         base_bias=float(src.get("bias", 0)),
                         kind=src.get("kind", "br"))
                longform_extra.append(a)
    stories = attach_longreads(stories, news + longform_extra, longform_ids,
                               use_embed=args.embed)
    stories = diversify_longreads(stories)
    source_meta = {s["id"]: s for s in sources}
    stories, world_extra = attach_world(stories, intl, use_embed=args.embed,
                                        source_meta=source_meta)
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
    # C-1: leituras da semana (janela própria, independente do matching)
    lr_links = {x["link"] for s in stories for x in s.get("longreads", [])}
    leituras = build_leituras(store, sources, days=10, limit=8,
                              exclude_links=lr_links, stories=stories)
    if leituras:
        print(f"[3e/4] {len(leituras)} leituras da semana")
    if checks:
        print(f"[3d/4] {len(matches)} matéria(s) casaram com checagens nesta rodada")

    os.makedirs(SITE, exist_ok=True)
    # F-03: ids estáveis; aliases preservam links ?story= da rodada anterior
    prev_stories = []
    prev_path = os.path.join(SITE, "data.json")
    if os.path.exists(prev_path):
        try:
            with open(prev_path, encoding="utf-8") as f:
                prev_stories = json.load(f).get("stories", [])
        except Exception:
            prev_stories = []
    stories = assign_aliases(stories, prev_stories)
    # A-6: identidade/membros/eventos persistentes + aliases de rodadas antigas
    if store is not None:
        store.sync_stories(stories, run_ts)
        db_aliases = store.aliases_map()
        for s in stories:
            aliases = set(s.get("aliases") or []) | set(db_aliases.get(s["id"], []))
            if aliases:
                s["aliases"] = sorted(aliases)
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
               "leituras": leituras,
               "front_only": front_only,
               "front_pautas": pautas,
               "front_pages": front_stats,
               "only_world": world_extra.get("only_world", []),
               "brasil_abroad": world_extra.get("brasil_abroad", []),
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
        pc = s["pct"]
        print(f"  [{s['counts']['total']:2}x "
              f"E{(pc.get('L',0)+pc.get('CL',0)):2}% "
              f"C{pc.get('C',0):2}% "
              f"D{(pc.get('R',0)+pc.get('CR',0)):2}%] {s['title'][:80]}")


SITE_URL = os.environ.get("BALANCO_SITE_URL",
                              "https://hcarta.github.io/balanco").rstrip("/")
ARCHIVE_KEEP = 90  # edições diárias mantidas


def _slim_payload(payload: dict) -> dict:
    """F-15: arquivo diário só com o necessário para reler a edição."""
    keep_story = ("id", "title", "summary", "section", "section_label",
                  "avg_bias", "counts", "pct", "blindspot", "updated", "aliases")
    keep_art = ("source", "title", "link", "bucket", "bias")
    return {
        "generated_at": payload.get("generated_at"),
        "n_stories": payload.get("n_stories"),
        "stories": [
            {**{k: s.get(k) for k in keep_story if k in s},
             "articles": [{k: a.get(k) for k in keep_art if k in a}
                          for a in s.get("articles", [])]}
            for s in payload.get("stories", [])
        ],
    }


def archive_snapshot(site_dir: str, payload: dict) -> str | None:
    """Guarda uma edição por dia em arquivo/AAAA-MM-DD.json (Fase 6.1)."""
    import glob
    adir = os.path.join(site_dir, "arquivo")
    os.makedirs(adir, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dest = os.path.join(adir, f"{day}.json")
    if not os.path.exists(dest):
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(_slim_payload(payload), f, ensure_ascii=False)
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
