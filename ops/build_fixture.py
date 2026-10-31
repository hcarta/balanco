#!/usr/bin/env python3
"""F-12: congela um corpus mínimo para os portões de teste.

O CI sobrescreve `docs/data.json` a cada 30 min; um teste que lê esse arquivo
muda de resultado conforme a rodada. Este script extrai só títulos (histórias,
matérias e checagens) para `tests/fixtures/corpus_AAAA-MM-DD.json`, que é
versionado e estável.

Uso: python ops/build_fixture.py [--date AAAA-MM-DD]
"""
import argparse
import json
import os
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()

    with open(os.path.join(BASE, "docs", "data.json"), encoding="utf-8") as f:
        payload = json.load(f)

    stories = []
    for s in payload.get("stories", []):
        stories.append({
            "title": s.get("title", ""),
            "articles": [{"title": a.get("title", "")} for a in s.get("articles", [])],
        })
    checks = [{"title": c.get("title", "")} for c in payload.get("factchecks", [])]
    out = {
        "meta": {
            "frozen_at": args.date,
            "source": "docs/data.json",
            "n_stories": len(stories),
            "n_articles": sum(len(s["articles"]) for s in stories),
            "n_factchecks": len(checks),
            "note": "Corpus congelado para testes; não atualizar a cada rodada.",
        },
        "stories": stories,
        "factchecks": checks,
    }
    dest = os.path.join(BASE, "tests", "fixtures", f"corpus_{args.date}.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"{dest}: {len(stories)} histórias, "
          f"{out['meta']['n_articles']} matérias, {len(checks)} checagens")


if __name__ == "__main__":
    main()
