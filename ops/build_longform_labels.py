"""Gera tests/longform_pairs.jsonl (3 níveis) a partir do não-rotulado.

Rotulagem única (agente), 01/11/2026. Critério:
  2 = a peça trata do mesmo fato/desdobramento da história;
  1 = pano de fundo útil (pessoa/instituição/tema), sem cobrir o fato;
  0 = irrelevante ou só o mesmo nome/tema amplo.
"""
import json
from pathlib import Path

P = [json.loads(l) for l in Path("tests/longform_pairs_unlabeled.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

# old=1 -> 2 por padrão; estes positivos são contexto, não o mesmo fato
CONTEXT = {
    "LF006", "LF008", "LF009", "LF012", "LF013", "LF014", "LF015",
    "LF018", "LF023", "LF024", "LF029", "LF046", "LF051", "LF054",
}
# old=0 mas têm valor de pano de fundo
CONTEXT_OLD0 = {"LF022", "LF050"}
# same fact que o binário marcou como redundante/sem contexto
SAME = {"LF011", "LF019", "LF030", "LF032", "LF038"}
# piauí / extras
SAME |= {"LF067", "LF069", "LF091"}
CONTEXT |= {"LF065", "LF066", "LF070", "LF098", "LF103", "LF104",
            "LF106", "LF116", "LF118"}

for p in P:
    pid = p["id"]
    if pid in SAME:
        p["label"] = 2
    elif pid in CONTEXT or pid in CONTEXT_OLD0:
        p["label"] = 1
    elif p.get("legacy_label") == 1:
        p["label"] = 2
    else:
        p["label"] = 0
    p["relation"] = {2: "same", 1: "background", 0: "none"}[p["label"]]

out = Path("tests/longform_pairs.jsonl")
out.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in P) + "\n",
               encoding="utf-8")
from collections import Counter
print(len(P), Counter(p["label"] for p in P), "piauí",
      sum(p["piece_source"] == "Revista piauí" for p in P))
