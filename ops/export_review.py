#!/usr/bin/env python3
"""Fila de revisão humana das checagens (Fase 4.5).

Lê state/factcheck_ledger.json e gera state/revisao_checagens.csv:
uma linha por casamento matéria x checagem, com veredito e links.
Uso: python ops/export_review.py
"""
import csv
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LEDGER = os.path.join(BASE, "state", "factcheck_ledger.json")
OUT = os.path.join(BASE, "state", "revisao_checagens.csv")


def main():
    try:
        with open(LEDGER, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print("ledger ainda não existe — rode python app.py primeiro")
        return
    matches = data.get("matches", [])
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fonte", "veredito", "score", "termos", "data_checagem",
                    "matéria", "link_matéria", "checagem", "link_checagem", "checador"])
        for m in sorted(matches, key=lambda x: (x.get("verdict", ""), x.get("source_id", ""))):
            w.writerow([m.get("source"), m.get("verdict"), m.get("score"),
                        m.get("terms", ""), (m.get("date") or "")[:10],
                        m.get("article"), m.get("article_link"),
                        m.get("check"), m.get("check_link"), m.get("checker")])
    by_src = {}
    for s, st in data.get("sources", {}).items():
        if st.get("total"):
            by_src[s] = st
    print(f"{len(matches)} casamentos → {OUT}")
    for s, st in sorted(by_src.items()):
        flag = " ← REVISAR" if st.get("revisar") else ""
        print(f"  {s}: {st['total']} (falso={st.get('falso',0)} enganoso={st.get('enganoso',0)}){flag}")


if __name__ == "__main__":
    sys.exit(main())
