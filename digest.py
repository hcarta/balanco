"""Backlog item 5: week_digest, métricas diárias e acompanhamento de pautas.

Arquivos (estado local, persistido pelo cache/commit diário do CI):
  state/metrics/AAAA-Www.json   — métricas por dia (notícias)
  state/week_digest.json.gz     — recorte slim dos últimos 7 dias
  state/pautas_metrics.json     — acompanhamento das pautas de capa
"""
import gzip
import json
import os
import re
import statistics
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
BUCKETS = ("L", "CL", "C", "CR", "R")
_NUM_RE = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")


def _now(now=None):
    return now or datetime.now(timezone.utc)


def _ts(s):
    for k in ("updated", "generated_at"):
        v = s.get(k)
        if not v:
            continue
        try:
            return datetime.fromisoformat(
                str(v).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return 0.0


def story_metrics(stories):
    """Métricas comparáveis de uma rodada (todas as histórias)."""
    n = len(stories)
    inds = [int((s.get("counts") or {}).get("independent", 0) or 0)
            for s in stories]
    blind = sum(1 for s in stories if s.get("blindspot"))
    longr = sum(1 for s in stories if s.get("longreads"))
    avg = {}
    for b in BUCKETS:
        vals = [float((s.get("pct") or {}).get(b, 0) or 0) for s in stories]
        avg[b] = round(sum(vals) / n, 1) if n else 0.0
    return {
        "n_stories": n,
        "n_articles": sum(int((s.get("counts") or {}).get("articles", 0) or 0)
                          for s in stories),
        "median_independent": round(statistics.median(inds), 1) if inds else 0,
        "pct_blindspot": round(100 * blind / n, 1) if n else 0.0,
        "pct_longread": round(100 * longr / n, 1) if n else 0.0,
        "avg_pct": avg,
    }


def _week(dt):
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _atomic_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def update_metrics(stories, base=None, now=None):
    """Grava as métricas do dia (última rodada vence) e devolve a série."""
    now = _now(now)
    base = base or os.path.join(BASE, "state", "metrics")
    m = {**story_metrics(stories),
         "date": now.date().isoformat(),
         "generated_at": now.isoformat()}
    week = _week(now)
    path = os.path.join(base, f"{week}.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        data = {"week": week, "days": {}}
    data.setdefault("days", {})[m["date"]] = m
    _atomic_json(path, data)
    return {"week": week, "today": m,
            "series": load_metrics_series(base, days=7, now=now)}


def load_metrics_series(base=None, days=7, now=None):
    base = base or os.path.join(BASE, "state", "metrics")
    rows = []
    try:
        files = [f for f in os.listdir(base) if f.endswith(".json")]
    except FileNotFoundError:
        return []
    for name in files:
        try:
            with open(os.path.join(base, name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        rows.extend(data.get("days", {}).values())
    rows.sort(key=lambda x: x.get("date", ""))
    return rows[-days:]


def auto_summary(s):
    """Resumo automático (regras/lead), rotulado como automático no digest."""
    txt = (s.get("summary") or "").strip()
    if txt:
        cut = txt[:240].rsplit(" ", 1)[0]
        return cut + ("…" if len(txt) > 240 else "")
    n = int((s.get("counts") or {}).get("total", 0) or 0)
    g = int((s.get("counts") or {}).get("independent", 0) or 0)
    return f"{s.get('title', '')} — {n} coberturas, {g} grupos independentes."


def _digest_entry(s):
    from app import entities, numbers
    c = s.get("counts") or {}
    links = [a.get("link") for a in (s.get("articles") or [])
             if a.get("link")][:5]
    lrs = [x.get("link") for x in (s.get("longreads") or [])
           if x.get("link")][:3]
    return {
        "id": s.get("id"),
        "date": (s.get("updated") or "")[:10],
        "title": s.get("title", ""),
        "section": s.get("section_label", ""),
        "counts": {"total": c.get("total", 0),
                   "independent": c.get("independent", 0),
                   "frames": c.get("frames", 0),
                   "articles": c.get("articles", 0),
                   "groups": {b: (c.get("groups") or {}).get(b, 0)
                              for b in BUCKETS}},
        "pct": {b: (s.get("pct") or {}).get(b, 0) for b in BUCKETS},
        "blindspot": s.get("blindspot"),
        "entities": sorted(entities(s.get("title", "")))[:8],
        "numbers": sorted(numbers(s.get("title", "")))[:6],
        "links": links,
        "longreads": lrs,
        "auto_summary": auto_summary(s),
        "auto": True,
    }


def build_week_digest(stories, path=None, now=None, days=7, cap=1500):
    """Recorte slim dos últimos 7 dias em gzip (reprodutível do snapshot)."""
    now = _now(now)
    cutoff = now.timestamp() - days * 24 * 3600
    picked = [s for s in stories if _ts(s) >= cutoff][:cap]
    data = {"generated_at": now.isoformat(), "days": days,
            "stories": [_digest_entry(s) for s in picked]}
    path = path or os.path.join(BASE, "state", "week_digest.json.gz")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)
    return len(picked)


def update_pautas_metrics(entry, path=None, now=None):
    """Série diária do acompanhamento das pautas de capa."""
    now = _now(now)
    path = path or os.path.join(BASE, "state", "pautas_metrics.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        data = {"days": {}}
    row = {**entry, "date": now.date().isoformat(),
           "generated_at": now.isoformat()}
    data.setdefault("days", {})[row["date"]] = row
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic_json(path, data)
    rows = sorted(data["days"].values(), key=lambda x: x.get("date", ""))
    return {"today": row, "series": rows[-7:]}
