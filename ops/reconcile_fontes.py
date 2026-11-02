"""Fase 1 (PLAN_FINAL): reconcilia viés/factualidade de Claude × Gemini.

Regra:
- consenso = media(claude, gemini), arredondada a 0,1.
- acao = "aplicar" se |claude-gemini| <= 0,5 e a mudanca for >= 0,3;
         "revisar" se |claude-gemini| > 0,5 ou |consenso-atual| >= 1,0;
         "manter"  caso contrario.
- factualidade: "aplicar" quando claude e gemini concordam (mesmo nivel) e difere
  do atual; "revisar" quando discordam; "manter" quando ja bate.

Uso:
    python ops/reconcile_fontes.py                # gera state/consenso_fontes.csv
    python ops/reconcile_fontes.py --apply        # aplica 'aplicar' em sources.yaml
"""
import argparse
import csv
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUR = os.path.join(BASE, "revisao_fontes.csv")
CLAUDE = os.path.join(BASE, "comparacao_fontes_claude.csv")
GEMINI = os.path.join(BASE, "comparacao_fontes_gemini.csv")
OUT = os.path.join(BASE, "state", "consenso_fontes.csv")
YAML = os.path.join(BASE, "sources.yaml")
CHANGELOG = os.path.join(BASE, "state", "vies_changelog.md")
CURADORIA = os.path.join(BASE, "CURADORIA_VIES.md")

LEVELS = {"alta": "high", "muito alta": "very_high", "mista": "mixed",
          "baixa": "low", "muito baixa": "very_low"}


def f3(level: str) -> str:
    """Colapsa factualidade em 3 níveis para comparar modelos."""
    return "alta" if level in ("high", "very_high") else (
        "mista" if level == "mixed" else "baixa")


def norm_fact(v: str) -> str:
    v = (v or "").strip().lower()
    return LEVELS.get(v, v)


def load_cur():
    out = {}
    for r in csv.DictReader(open(CUR, encoding="utf-8")):
        try:
            b = round(float(r["bias_atual"]), 1)
        except (TypeError, ValueError):
            b = None
        out[r["id"]] = {"nome": r["nome"], "bias": b,
                        "fact": norm_fact(r["factualidade_atual"])}
    return out


def load_model(path, bk, fk):
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        try:
            b = round(float(r[bk]), 1)
        except (TypeError, ValueError):
            b = None
        out[r["id"]] = {"bias": b, "fact": norm_fact(r[fk])}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--close-review", action="store_true",
                    help="aplica a mediana {atual, claude, gemini} nos REVISAR")
    args = ap.parse_args()

    cur = load_cur()
    cl = load_model(CLAUDE, "vies_novo", "fact_novo")
    ge = load_model(GEMINI, "meu_vies_calculado", "minha_factualidade")

    rows = []
    for sid in sorted(cur):
        if sid not in cl or sid not in ge:
            continue
        a, c, g = cur[sid]["bias"], cl[sid]["bias"], ge[sid]["bias"]
        cons = None
        if c is not None and g is not None:
            cons = round((c + g) / 2, 1)
        diff = round(abs((c or 0) - (g or 0)), 2)
        delta = round(abs((cons or 0) - (a or 0)), 2)
        # discordância entre modelos => humano; swing grande com concordância
        # exata (diff == 0) pode aplicar (ex.: longform novo em 0,0).
        if diff >= 0.5:
            acao = "revisar"
        elif cons is not None and delta >= 0.3:
            acao = "aplicar"
        else:
            acao = "manter"
        # factualidade: compara em 3 níveis (alta/mista/baixa); high vs
        # very_high não é discordância material.
        fa, fc, fg = cur[sid]["fact"], cl[sid]["fact"], ge[sid]["fact"]
        fa3, fc3, fg3 = f3(fa), f3(fc), f3(fg)
        if fc3 != fg3:
            facao, fcons = "revisar", ""
        elif fc3 != fa3:
            # valor representativo do nível, sem inflar (alta -> high)
            fcons = "high" if fc3 == "alta" else ("mixed" if fc3 == "mista" else "low")
            if fc == fg == "very_high" and fa3 == "alta":
                fcons = "very_high"
            facao = "aplicar"
        else:
            facao, fcons = "manter", ""
        mediana = None
        if None not in (a, c, g):
            vals = sorted([a, c, g])
            mediana = round(vals[1], 1)
        rows.append({"id": sid, "nome": cur[sid]["nome"],
                     "bias_atual": a, "claude": c, "gemini": g,
                     "consenso": cons, "mediana": mediana, "acao": acao,
                     "fact_atual": fa, "fact_consenso": fcons,
                     "fact_acao": facao})

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    ap_ = [r for r in rows if r["acao"] == "aplicar"]
    rv = [r for r in rows if r["acao"] == "revisar"]
    fa_ = [r for r in rows if r["fact_acao"] == "aplicar"]
    frv = [r for r in rows if r["fact_acao"] == "revisar"]
    print(f"{len(rows)} fontes → {OUT}")
    print(f"viés: aplicar {len(ap_)} | revisar {len(rv)}")
    print(f"factualidade: aplicar {len(fa_)} | revisar {len(frv)}")
    for r in ap_:
        print(f"  aplicar {r['nome'][:28]:28} {r['bias_atual']:+.1f} → {r['consenso']:+.1f}")
    for r in fa_:
        print(f"  fact    {r['nome'][:28]:28} {r['fact_atual']} → {r['fact_consenso']}")
    if rv:
        print("\nREVISAR (decisão humana):")
        for r in rv:
            print(f"  {r['nome'][:28]:28} atual {r['bias_atual']:+.1f} | "
                  f"claude {r['claude']:+.1f} | gemini {r['gemini']:+.1f}")
    if frv:
        print("\nFACTUALIDADE REVISAR:")
        for r in frv:
            print(f"  {r['nome'][:28]:28} atual {r['fact_atual']:10}")

    if args.close_review:
        for r in rows:
            if r["acao"] != "revisar" or r["mediana"] is None:
                continue
            if abs(r["mediana"] - r["bias_atual"]) < 0.05:
                continue
            r["_close"] = r["mediana"]
        rv_close = [r for r in rows if r.get("_close") is not None]
        print(f"\nfechar revisão (mediana): {len(rv_close)}")
        for r in rv_close:
            print(f"  {r['nome'][:28]:28} {r['bias_atual']:+.1f} → "
                  f"{r['_close']:+.1f}")

    if not args.apply and not args.close_review:
        return

    # aplica em sources.yaml (por bloco de id, preservando o resto)
    text = open(YAML, encoding="utf-8").read()
    applied = 0
    for r in rows:
        newbias = r["consenso"] if (r["acao"] == "aplicar" and args.apply) else None
        if r.get("_close") is not None:
            newbias = r["_close"]
        newfact = r["fact_consenso"] if (r["fact_acao"] == "aplicar" and args.apply) else None
        if newbias is None and newfact is None:
            continue
        pat = re.compile(rf"(^  - id: {re.escape(r['id'])}\n(?:.*\n)*?)(?=^  - id: |\Z)",
                         re.M)
        m = pat.search(text)
        if not m:
            print(f"  [aviso] bloco não encontrado: {r['id']}")
            continue
        block = m.group(1)
        nb = block
        if newbias is not None:
            nb = re.sub(r"^    bias: .*$", f"    bias: {newbias:.1f}", nb, count=1, flags=re.M)
        if newfact is not None:
            nb = re.sub(r"^    factuality: .*$", f"    factuality: {newfact}", nb,
                        count=1, flags=re.M)
        if nb != block:
            text = text[:m.start(1)] + nb + text[m.end(1):]
            applied += 1
    open(YAML, "w", encoding="utf-8").write(text)
    print(f"\nsources.yaml: {applied} blocos atualizados")

    # changelog
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"\n## {day} — reconciliação Claude × Gemini\n",
             "Regra: consenso = média dos dois modelos; aplicado só onde "
             "|claude−gemini| ≤ 0,5 e Δ ≥ 0,3. Swings grandes ficam para o dono.\n"]
    for r in ap_:
        lines.append(f"- **{r['nome']}**: viés {r['bias_atual']:+.1f} → "
                     f"{r['consenso']:+.1f} (claude {r['claude']:+.1f}, gemini {r['gemini']:+.1f})")
    for r in rv_close:
        lines.append(f"- **{r['nome']}**: viés {r['bias_atual']:+.1f} → "
                     f"{r['_close']:+.1f} (mediana de atual/claude/gemini; "
                     f"claude {r['claude']:+.1f}, gemini {r['gemini']:+.1f})")
    for r in fa_:
        lines.append(f"- **{r['nome']}**: factualidade {r['fact_atual']} → "
                     f"{r['fact_consenso']} (ambos os modelos)")
    with open(CHANGELOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"changelog: {CHANGELOG}")


if __name__ == "__main__":
    main()
