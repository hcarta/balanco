# Balanço — pacote para revisão por modelo maior (01/11/2026)

> Use os arquivos-fonte, não este resumo, como verdade. Este documento é só o mapa.

## 1. O que é

Agregador brasileiro de notícias (estilo Ground.news), estático, sem paywall-bypass,
sem LLM em produção. `sources.yaml` → `collectors.py` (RSS/sitemap) → `store.py`
(SQLite) → `app.py` (cluster TF-IDF → consolidação → pautas/hubs → longform →
Lá fora → checagens) → `docs/data.json` → `docs/index.html`. CI a cada 30 min
(GitHub Actions, deploy-pages). Viés **fixo por fonte**; LLM só opt-in.

## 2. Estado (medido, não estimado)

- 53 fontes (36 BR + 16 intl + 1? ver `revisao_fontes.csv`); ~440 histórias/rodada.
- **Testes: 141 passed + 56 xfailed** (`python -m pytest tests/ -q`).
- Cluster lexical com âncora de entidade; `--embed-cluster` experimental (over-merge 645).
- `--embed` (ONNX/fastembed, CI) ativo nas conexões longform/internacional.
- C-3 híbrido integrado no Aprofunde-se (P@3 0,56, 17 histórias/rodada).
- Filtros de serviço: loteria/horóscopo/previsão/calendários; Foro de Teresina = podcast.
- Pautas: entidade como assunto + lugar não é pauta; Aprofunde-se/Lá fora/Outros em `<details>`.
- Analytics local (`?uso=1`, sem rede). F-13 deploy-pages + commit diário com retry.

## 3. Documentos (ordem de leitura)

1. `PLAN_CLAUDE.md` — diagnóstico original + status de cada fase.
2. `PLANO_CONEXOES.md` — F1–F4 das conexões (longform/internacional/checagens).
3. `PLAN_FALSAS_EQUIVALENCIAS.md` — gate de par do cluster (F0–F5).
4. `PLAN_F2_DIAGNOSTICO.md` — **por que o treino F2 falhou** + caso-âncora safra Trump × Papa.
5. `revisao_fontes.csv` — 53 fontes (viés/factualidade atuais = alegações a revisar).
6. Conjuntos: `tests/cluster_pairs.jsonl` (154), `tests/longform_pairs.jsonl` (120),
   `tests/conn_pairs.jsonl` (167), `tests/longform_pairs_unlabeled.jsonl`.

## 4. Decisões abertas (o que a revisão deve arbitrar)

1. **F3: gate duro vs veto.** O modelo (AUC 0,835) não atinge P≥0,97/R≥0,80. Como gate
   duro fragmenta (R~0,3); como **veto** (rejeitar se P(same)<~0,2) quebraria pontes
   tipo safra Trump×Papa sem custo de recall. Nenhum dos dois foi implementado.
2. **Fronteira same×related.** A classe `related` é lexicamente quase idêntica a `same`
   só com títulos. Opções no diagnóstico §6: resumos como sinal, feature de verbo,
   expandir F1 a 600, ou aceitar gate conservador (P~0,93/R~0,43).
3. **`tfidf_matrix`**: simplificar (`min_df=1`) muda todos os cossenos e recalibraria
   limiares 0,38/0,62 — fazer ou descartar?
4. **Bug de instrumentação confirmado**: `dt_hours` constante 0 no treino F2
   (`_ts_of` lê `updated` de história). Refazer features com `published` antes de
   qualquer conclusão sobre valor do sinal temporal.
5. **Viés/factualidade das 53 fontes** (`revisao_fontes.csv`): foi curadoria de um
   anotador (dono). Pedir 2+ modelos independentes e reportar concordância.

## 5. Reprodução

```bash
pip install -r requirements.txt -r requirements-embed.txt
python -m pytest tests/ -q
python ops/eval_longform.py --embed
python ops/eval_pair_model.py --pairs tests/cluster_pairs.jsonl --seed 7
FASTEMBED_CACHE_PATH=state/models python app.py --body --body-cap 40 --embed
python -m http.server -d docs 8003
```

## 6. Fora do escopo da revisão

Newsletter (sem provedor de e-mail); login da piauí (termos/segurança);
`--embed-cluster` (experimental, over-merge documentado).
