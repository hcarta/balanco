# F2 — Diagnóstico do treino do gate de par (para avaliação futura)

> Estado em 01/11/2026. Treino executado, **aceite não atingido**, F3 bloqueado.
> Este arquivo existe para que outro agente avalie com precisão o que falhou,
> o que é ruído de instrumentação e o que é limite real do problema.

## 1. O problema

Trocar a heurística de fusão do cluster (`_pair_ok`: TF-IDF + tokens + âncora
de entidade) por um classificador de par calibrado, sem perder precisão.
Uso no cluster: fundir **só** pares `same` (mesmo acontecimento); `related`
(mesmo tema, ato distinto) e `different` **não** podem fundir.

## 2. Dados

- `tests/cluster_pairs.jsonl`: **154 pares** (83 same / 36 related / 35 different).
  138 amostrados do audit F0 (estratos: fundidos de baixo cosseno, quase-duplicatas,
  zona 0,30–0,45, negativos difíceis, mesma-fonte) + 16 seed manual.
- Rotulagem: **anotador único (agente)**. Regra: `same` = mesmo ator + mesmo ato +
  mesma janela; desdobramento posterior = `related` (ex.: retomada de saques após
  o ataque); edições distintas do mesmo programa = `different`.
- `tests/cluster_pairs_seed.jsonl` (16 originais) e
  `tests/cluster_pairs_unlabeled.jsonl` (138 sem rótulo) preservados.
- `state/pair_features.jsonl`: 19 features por par (gerar com
  `python ops/pair_features.py --pairs tests/cluster_pairs.jsonl --out … [--embed]`).

## 3. Setup do treino (`ops/eval_pair_model.py`)

- Alvo binário: same=1, resto=0. `LogisticRegression(C=1.0, class_weight=balanced)`,
  features padronizadas (mean/scale salvos no JSON do modelo).
- **Split por componentes de títulos compartilhados** (35 títulos aparecem em >1
  par; ex.: o explainer de assédio eleitoral está em 6 pares). Split por data é
  **inviável**: os 154 pares vêm de uma única janela de 72 h. Seed 7 →
  train 101 (53 same) / test 53 (30 same).
- `cos_emb` incluído (features geradas com `--embed`); sem `--embed` ele é
  sentinela -1 e sai do vetor.

## 4. Resultados (com embeddings)

| Ponto | train | test |
|---|---|---|
| AUC | 0,900 | 0,835 |
| thr 0,5 | P 0,87 R 0,75 | P 0,78 R 0,70 |
| thr 0,7 | P 0,92 R 0,68 | P 0,81 R 0,57 |
| thr 0,91 (P≥0,97) | P 1,00 R 0,25 | P 1,00 R 0,30 |
| regra atual | P 0,67 R 0,64 | P 0,74 R 0,67 |

- **Aceite exigia P≥0,97 e R≥0,80: não atingido** (R≈0,30 no ponto P=1,00).
- 4 `different` com p≥0,5: Jornal da Noite 31×30 (0,90), Finados missas×rodovias
  (0,77), bebês 12d×34d (0,70), trios de furto (0,53).
- Coeficientes (top |.|): `same_group −1,26`, `cov_long +1,15`, `cos_tfidf +1,30`,
  `cov_short −0,82`, `subject_match +0,74`, `shared_numbers −0,44`,
  `cos_emb +0,43`, `shared_multi −0,32`.
- O modelo **domina a regra na curva PR** (a P≈0,70: R 0,87 vs 0,67), mas a
  classe `related` é lexicamente quase idêntica a `same` só com títulos.

## 5. Bugs e armadilhas de instrumentação (não são limite real)

1. **`dt_hours` é constante 0 no treino — BUG.** Os scripts F0/F1 preencheram
   `ts` com `app._ts_of(article)`, mas `_ts_of` lê o campo `updated` (de
   história), retornando 0,0 para artigos. Artigos têm `published`/`first_seen`;
   é preciso converter esses campos para timestamp ao gerar features. O sinal
   temporal (mesmo fato ≈ Δt pequeno) **nunca foi testado**.
2. **IDF dependente do corpus.** `cos_tfidf` e `cov` usam IDF do corpus em que a
   matriz é calculada: no harness do portão (308 títulos) os valores diferem do
   run real (5.000 artigos). 8 pares `different` fundidos no run real separam no
   harness — o FP é efeito de IDF/transitividade do corpus cheio, não do par
   isolado. Qualquer avaliação deve declarar o corpus.
3. **`same_group` = `source_id` no treino** (grupos editoriais reais não foram
   resolvidos). O coeficiente negativo reflete o dataset: pares mesma-fonte são
   muitas vezes `different` (séries da casa: Jornal da Noite 31×30, tarte
   tatin×coxinha, sushi). Com grupos reais (Globo, BBC) o sinal pode inverter.
4. **`shared_numbers` negativo** é em parte correto: pares `related` (Enem 34 mil
   × 5 mi, Fuvest) compartilham "2026"/"1º" com números divergentes — o modelo
   aprendeu "números em comum + resto diferente = related". Não remover sem
   separar `numbers_match` de `shared_numbers`.
5. **Limiares calibrados in-sample** (101 train). Qualquer re-treino deve manter
   split por componentes e reportar train/test.

## 6. Perguntas abertas para o próximo avaliador

1. O rótulo `related` é o gargalo? Testar alvo alternativo (same+related vs
   different) só como diagnóstico — para o cluster, `related` não pode fundir,
   então o binário atual está correto para o uso; a questão é se 154 pares
   bastam para a fronteira same×related.
2. Resumos (`summary`/`dek` do cache) como sinal: casos como bebês 12d×34d e
   Finados missas×rodovias provavelmente se resolvem com o dek. Custo: features
   passam a depender do cache, não só do título.
3. Verbo/predicado: pares same×related diferem no verbo ("vota"×"pede",
   "elege"×"vence" são mesmo fato; "registra"×"reforça" são atos distintos).
   Feature de verbo principal nunca foi tentada.
4. Ponto operacional: o gate precisa mesmo de R≥0,80? Erro de fragmentação
   (split) é seguro (visível, recuperável via consolidate/hub); erro de fusão
   corrompe o lado a lado. Um gate P~0,93/R~0,43 já é mais preciso que a regra
   (P~0,7) — ver §7 do plano-mãe antes de relaxar o aceite.
5. Expandir F1 a 600 pares (estratos originais) antes de qualquer conclusão sobre
   limite do problema: n=154 com 18 features é pouco para LR.

## 7. Caso-âncora: safra Trump × Papa (01/11/2026)

História “Trump promete US$ 15 bilhões para agricultores dos EUA…” (16 artigos)
fundiu com o bloco “Papa Leão XIV vota pelo correio…”. Diagnóstico par a par
(`_pair_decision`, harness de 16 docs):

- Nenhum par direto Trump-agro × Papa funde (cos 0,03–0,13, `low_sim`).
- A ponte é a Folha “Crítico de Trump, Leão 14 vota pelo correio nas eleições
  de meio de mandato…”: funde com 2 peças do Papa por `near_dup_ok`
  (cos 0,46 e 0,61; shared correio/eleições/eua/leão/vota [+mandato/meio]) —
  correto, o fato dela é o voto do papa.
- O elo indevido é ponte-Folha × Trump-agro: 5 tokens em comum
  (eleições/eua/mandato/meio/trump), cos 0,28 no harness (rejeitado) mas ≥0,38
  no corpus cheio (IDF dependente do corpus, §5.2) → cadeia single-link fecha.
- `_cohere` não salvou: a similaridade com o medoide se manteve.

Rótulo para o conjunto: ponte-Folha × Trump-agro = `related` (macro-tema
midterms, atos distintos: voto × subsídios). O gate F3 como **veto**
(rejeitar se P(same) < ~0,2) quebraria a cadeia sem custo de recall; como gate
duro (P≥0,97) fragmentaria. Decisão de desenho pendente na revisão.

## 8. Reprodução

```bash
python ops/pair_features.py --pairs tests/cluster_pairs.jsonl --out state/pair_features.jsonl --embed  # 19 features
python ops/eval_pair_model.py --pairs tests/cluster_pairs.jsonl --seed 7          # métricas
python ops/eval_pair_model.py --pairs tests/cluster_pairs.jsonl --seed 7 --save state/pair_model.json
python -m pytest tests/test_cluster_pairs.py tests/test_pair_features.py -q 2>/dev/null || python -m pytest tests/test_cluster_pairs.py -q
```

Arquivos: `ops/eval_pair_model.py`, `ops/pair_features.py`,
`ops/audit_pairs.py`, `tests/cluster_pairs*.jsonl`,
`tests/test_cluster_pairs.py` (portão: different estrito, MUST_FUSE 27,
56 KNOWN_FN como xfail), `app.py::_pair_decision` (regra atual com motivos).
Plano-mãe: `PLAN_FALSAS_EQUIVALENCIAS.md` (F3 bloqueado até decisão sobre §6.4).
