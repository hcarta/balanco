#!/usr/bin/env python3
"""Relatório rápido: métricas da semana e acompanhamento das pautas de capa.

Uso: python3 report.py [--json]
Lê state/metrics/*.json e state/pautas_metrics.json (gerados a cada rodada).
"""
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def metrics_rows():
    rows = []
    for path in glob.glob(os.path.join(BASE, "state", "metrics", "*.json")):
        rows.extend((_load(path).get("days") or {}).values())
    return sorted(rows, key=lambda x: x.get("date", ""))


def pautas_rows():
    data = _load(os.path.join(BASE, "state", "pautas_metrics.json"))
    return sorted((data.get("days") or {}).values(),
                  key=lambda x: x.get("date", ""))


def main(argv):
    m = {x.get("date"): x for x in metrics_rows()}
    p = {x.get("date"): x for x in pautas_rows()}
    dates = sorted(set(m) | set(p))[-7:]
    if "--json" in argv:
        print(json.dumps({"noticias": [m[d] for d in dates if d in m],
                          "pautas": [p[d] for d in dates if d in p]},
                         ensure_ascii=False, indent=1))
        return 0
    print("Data       Histórias  Grupos  Blind  Longas  Sem pauta  Emerg  Reus  Pautas")
    print("---------  ---------  ------  -----  ------  ---------  -----  ----  ------")
    for d in dates:
        a, b = m.get(d, {}), p.get(d, {})
        print(f"{d}  {a.get('n_stories', '—'):>9}  "
              f"{a.get('median_independent', '—'):>6}  "
              f"{a.get('pct_blindspot', '—'):>4}%  "
              f"{a.get('pct_longread', '—'):>5}%  "
              f"{b.get('unmatched_rate', '—'):>8}%  "
              f"{b.get('n_emergent', '—'):>5}  "
              f"{b.get('n_reused', '—'):>4}  "
              f"{b.get('n_pautas', '—'):>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
