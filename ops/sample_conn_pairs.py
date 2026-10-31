#!/usr/bin/env python3
"""Amostra pares para calibrar as conexões notícia↔longform / ↔internacional /
↔checagem (F1.2).

Por que não amostrar ao acaso: os positivos são raros (11 conexões de
aprofundamento em 102 histórias × 85 peças). Amostra aleatória daria quase só
negativos e não calibraria nada.

A amostra sai do **pré-filtro** — pares que compartilham ao menos uma entidade
ou têm cobertura de título >= 0.12. É a distribuição que o scorer verá em
produção, então P/R medidos aqui valem para o ponto de operação real (e não
para "todos os pares possíveis", que ninguém consulta).

Estratos (por sinal barato, nunca pelo score final):
  high — entidade em comum E cobertura >= 0.25
  mid  — entidade em comum OU cobertura >= 0.30
  low  — restante do pré-filtro

Saída: tests/conn_pairs_unlabeled.jsonl (label=null). Rotular à mão em
tests/conn_pairs.jsonl. O score NÃO vai para o arquivo: rotular olhando o
score seria circular.
"""
import json
import os
import random
import sqlite3
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import app  # noqa: E402

SEED = 42
N = {"longform": 60, "intl": 40, "check": 30}
POOL_DAYS = {"longform": 7, "intl": 3}


def load_stories():
    with open(os.path.join(BASE, "docs", "data.json"), encoding="utf-8") as f:
        data = json.load(f)
    return [s for s in data["stories"] if s.get("title")]


def load_pool(kind):
    db = sqlite3.connect(os.path.join(BASE, "state", "cache.db"))
    cutoff = time.time() - POOL_DAYS[kind] * 86400
    if kind == "longform":
        with open(os.path.join(BASE, "sources.yaml"), encoding="utf-8") as f:
            import yaml
            srcs = yaml.safe_load(f)["sources"]
        ids = [s["id"] for s in srcs if s.get("longform")]
        q = ",".join("?" * len(ids))
        rows = db.execute(
            f"SELECT title, link, source_id, summary FROM articles"
            f" WHERE source_id IN ({q}) AND ts > ?", (*ids, cutoff)).fetchall()
        names = {s["id"]: s["name"] for s in srcs}
        out = [{"title": r[0], "link": r[1], "source": names.get(r[2], r[2]),
                "summary": r[3] or ""} for r in rows]
        out = [a for a in out if not app.NON_JOURNALISM.search(a["title"])]
    else:
        rows = db.execute(
            "SELECT title, link, source_id, summary FROM articles WHERE ts > ?",
            (cutoff,)).fetchall()
        with open(os.path.join(BASE, "sources.yaml"), encoding="utf-8") as f:
            import yaml
            srcs = yaml.safe_load(f)["sources"]
        intl = {s["id"]: s["name"] for s in srcs if s.get("kind") == "intl"}
        out = [{"title": r[0], "link": r[1], "source": intl.get(r[2], r[2]),
                "summary": r[3] or ""} for r in rows if r[2] in intl]
    db.close()
    return out


def load_checks():
    from factcheck import fetch_all
    checks = fetch_all()
    return [{"title": c["title"], "link": c["link"],
             "source": c.get("checker", "checagem"), "summary": ""} for c in checks]


def stratum(ent_ok, cov):
    if ent_ok and cov >= 0.25:
        return "high"
    if ent_ok or cov >= 0.30:
        return "mid"
    return "low"


def main():
    random.seed(SEED)
    stories = load_stories()
    out = []
    for kind in ("longform", "intl", "check"):
        pool = load_checks() if kind == "check" else load_pool(kind)
        print(f"{kind}: {len(pool)} itens no pool, {len(stories)} histórias")
        buckets = {"high": [], "mid": [], "low": []}
        for s in stories:
            se = app.entities(s["title"])
            st = set(app.tok(s["title"]))
            for a in pool:
                ae = app.entities(a["title"])
                ent_ok, _ = app.entity_match(se, ae)
                cov = app._title_cov(st, set(app.tok(a["title"])))
                if not ent_ok and cov < 0.12:
                    continue
                b = stratum(ent_ok, cov)
                buckets[b].append({
                    "kind": kind,
                    "a_title": s["title"], "a_source": "Balanço",
                    "b_title": a["title"], "b_source": a["source"],
                    "b_link": a["link"], "b_summary": (a["summary"] or "")[:220],
                    "stratum": b, "label": None,
                })
        total = N[kind]
        per = [total // 3, total // 3, total - 2 * (total // 3)]
        picked = []
        for name, k in zip(("high", "mid", "low"), per):
            cand = buckets[name][:]
            random.shuffle(cand)
            picked += cand[:k]
            if len(cand) < k:
                print(f"  [aviso] estrato {name} tem {len(cand)}, pedidos {k}")
        # completa com o que sobrou, se algum estrato faltou
        if len(picked) < total:
            rest = [c for name in buckets for c in buckets[name] if c not in picked]
            random.shuffle(rest)
            picked += rest[: total - len(picked)]
        out += picked
    for i, p in enumerate(out):
        p["id"] = f"{p['kind'][:2].upper()}{i:03d}"
    path = os.path.join(BASE, "tests", "conn_pairs_unlabeled.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for p in out:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    from collections import Counter
    print(f"\n{len(out)} pares → {path}")
    print("por tipo/estrato:", Counter((p["kind"], p["stratum"]) for p in out))


if __name__ == "__main__":
    main()
