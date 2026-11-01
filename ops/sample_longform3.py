#!/usr/bin/env python3
"""Amostra pares história × longform para o conjunto C-3 (3 níveis).

- 60 pares do conjunto binário existente (história × longform), mantendo o
  `legacy_label` só como referência de rotulagem.
- 60 pares novos, sendo ≥40 com peças da piauí, amostrados do pré-filtro
  lexical (entidade OU cobertura >= 0,12) e de um controle aleatório.
- O arquivo de saída NÃO contém o score do scorer; só o estrato heurístico
  (same/background/hard/random) para estratificar a rotulagem.
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
import yaml  # noqa: E402

SEED = 11
N_TOTAL = 120
N_PIAUI = 58
random.seed(SEED)


def load_pieces():
    srcs = yaml.safe_load(open(os.path.join(BASE, "sources.yaml"),
                               encoding="utf-8"))["sources"]
    lf = {s["id"]: s for s in srcs if s.get("longform")}
    db = sqlite3.connect(os.path.join(BASE, "state", "cache.db"))
    cutoff = time.time() - 120 * 86400
    q = ",".join("?" * len(lf))
    rows = db.execute(
        f"SELECT link, source_id, title, summary, published, ts FROM articles"
        f" WHERE source_id IN ({q}) AND ts > ?", (*lf, cutoff)).fetchall()
    db.close()
    out = []
    for link, sid, title, summary, published, ts in rows:
        if not title or app.NON_JOURNALISM.search(title):
            continue
        if app.excluded_title(title):
            continue
        out.append({
            "link": link, "source_id": sid, "source_name": lf[sid]["name"],
            "title": title, "summary": app._clean_text(summary)[:300],
            "published": published, "ts": ts,
            "age_days": round(max(0, (time.time() - ts) / 86400), 1),
        })
    return out


def load_stories():
    with open(os.path.join(BASE, "docs", "data.json"), encoding="utf-8") as f:
        return [s for s in json.load(f)["stories"] if s.get("title")]


def stratum(story, piece, ok, cov):
    shared = app.entities(story["title"]) & app.entities(piece["title"])
    spec = app._distinct_entities(shared)
    if piece["age_days"] <= 14 and (cov >= 0.25 or len(spec) >= 2):
        return "same"
    if 14 < piece["age_days"] <= 120 and (cov >= 0.20 or len(spec) >= 2):
        return "background"
    if ok:
        return "hard"
    return "random"


def record(story, piece, ok, cov, legacy=None):
    return {
        "story_title": story["title"],
        "story_summary": (story.get("summary") or "")[:240],
        "piece_title": piece["title"],
        "piece_summary": piece["summary"],
        "piece_source": piece["source_name"],
        "piece_link": piece["link"],
        "piece_published": piece["published"],
        "age_days": piece["age_days"],
        "stratum": stratum(story, piece, ok, cov),
        "legacy_label": legacy,
        "label": None,
    }


def main():
    pieces = load_pieces()
    stories = load_stories()
    by_link = {p["link"]: p for p in pieces}
    out, seen = [], set()

    # 1) pares binários existentes
    with open(os.path.join(BASE, "tests", "conn_pairs.jsonl"),
              encoding="utf-8") as f:
        old = [json.loads(l) for l in f if l.strip()]
    for p in old:
        if p.get("kind") != "longform":
            continue
        piece = by_link.get(p.get("b_link"))
        if not piece:
            continue
        story = {"title": p["a_title"], "summary": ""}
        ok, _ = app.entity_match(app.entities(story["title"]),
                                 app.entities(piece["title"]))
        cov = app._title_cov(set(app.tok(story["title"])),
                             set(app.tok(piece["title"])))
        key = (story["title"], piece["link"])
        if key in seen:
            continue
        seen.add(key)
        out.append(record(story, piece, ok, cov, p["label"]))

    # 2) pares novos, priorizando piauí
    piaui = [p for p in pieces if p["source_id"] == "piaui"]
    others = [p for p in pieces if p["source_id"] != "piaui"]
    piaui_pairs = []
    for piece in piaui:
        cands = []
        for story in stories:
            se, pe = app.entities(story["title"]), app.entities(piece["title"])
            ok, _ = app.entity_match(se, pe)
            cov = app._title_cov(set(app.tok(story["title"])),
                                 set(app.tok(piece["title"])))
            if ok or cov >= 0.12:
                cands.append((len(se & pe) + cov, ok, cov, story))
        cands.sort(key=lambda x: x[0], reverse=True)
        top = [c for c in cands[:2]]
        if stories:
            top.append((0, False, 0, random.choice(stories)))
        for _, ok, cov, story in top:
            key = (story["title"], piece["link"])
            if key in seen:
                continue
            seen.add(key)
            piaui_pairs.append((ok, cov, story, piece))
    random.shuffle(piaui_pairs)
    for ok, cov, story, piece in piaui_pairs[:N_PIAUI]:
        out.append(record(story, piece, ok, cov))

    # 3) completa com outros longforms do pré-filtro
    other_pairs = []
    for piece in others:
        for story in stories:
            se, pe = app.entities(story["title"]), app.entities(piece["title"])
            ok, _ = app.entity_match(se, pe)
            cov = app._title_cov(set(app.tok(story["title"])),
                                 set(app.tok(piece["title"])))
            if ok or cov >= 0.12:
                key = (story["title"], piece["link"])
                if key not in seen:
                    other_pairs.append((ok, cov, story, piece))
    random.shuffle(other_pairs)
    for ok, cov, story, piece in other_pairs:
        if len(out) >= N_TOTAL:
            break
        key = (story["title"], piece["link"])
        if key in seen:
            continue
        seen.add(key)
        out.append(record(story, piece, ok, cov))

    out = out[:N_TOTAL]
    for i, p in enumerate(out):
        p["id"] = f"LF{i:03d}"
    path = os.path.join(BASE, "tests", "longform_pairs_unlabeled.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for p in out:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    from collections import Counter
    print(f"{len(out)} pares → {path}")
    print("por fonte:", Counter(p["piece_source"] for p in out))
    print("por estrato:", Counter(p["stratum"] for p in out))
    print("piauí:", sum(p["piece_source"] == "Revista piauí" for p in out))


if __name__ == "__main__":
    main()
