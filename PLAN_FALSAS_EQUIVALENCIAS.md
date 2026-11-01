# Plano: eliminar falsas equivalências nas matérias

> Para o próximo modelo executar. Leia também `PLAN_CLAUDE.md` (contexto geral) e
> `PLANO_CONEXOES.md` (conexões longform/internacional, que **não** são o alvo aqui).

## 1. Objetivo

Hoje o agrupamento decide “mesma notícia” com regras heurísticas (TF-IDF + tokens +
âncora de entidade + coerência por medoide). O resultado é bom nos casos comuns, mas
ainda junta fatos distintos em três situações:

| Modo de falha | Exemplo real | Por que passou |
|---|---|---|
| **Tema genérico** | “Bulgária: eleição presidencial…” × “Flávio Bolsonaro admite disputar nova eleição presidencial” | 2 tokens de tema (`eleição`, `presidencial`) e cosseno 0,51 |
| **Entidade sozinha** | “Papa Leão XIV vota pelo correio” × “Papa Leão XIV pede paz na Ucrânia” | mesmo nome próprio, fato diferente |
| **Lugar como assunto** | pauta “Mato Grosso” com violência em MS + soja + TCE | estado é “onde”, não “sobre” |

Meta: **precisão primeiro**. Um artigo em história errada destrói a comparação lado a
lado e o blindspot; perder uma cobertura isolada é aceitável.

Não-objetivos: aumentar recall a qualquer custo, usar LLM por par em produção,
versionar `data.json`.

## 2. Diagnóstico (baseline medido em 01/11/2026)

Feed publicado: 405 histórias, 1.685 artigos de cobertura em histórias com 2+ veículos.

- **9%** dos artigos não compartilham nenhuma entidade com a manchete.
- **4,6%** não compartilham entidade **e** têm cosseno < 0,25 com a manchete
  (candidatos a falsa equivalência; parte é legítima em histórias multi-país,
  como a onda de protestos França/Alemanha).
- Correções já feitas: âncora de entidade + conteúdo além do nome (caso Bulgária),
  hub por assunto (pauta “Mato Grosso” eliminada via `HUB_STOP_GEO`).
- Regressões cobertas em `tests/test_matching.py` (123 testes).

O que falta: um critério **aprendido e mensurável** para o par, em vez de mais
heurísticas. Cada regra nova resolve um caso e arrisca outro; sem conjunto rotulado
não há como saber se o saldo é positivo.

## 3. Caminho recomendado

**Gate de par aprendido (pair model) sobre candidatos lexicais.**

1. O TF-IDF continua gerando **candidatos** (recall barato, roda em ms).
2. Um classificador de par decide **fundir ou não**, com features explícitas
   (entidades, números, sobreposição, tempo, seção, embedding).
3. Embeddings entram como **feature**, nunca como decisão isolada.
4. Coerência por medoide continua como rede de segurança.

Por que este caminho:

- mede precisão e recall em conjunto fixo, então cada mudança é comparável;
- explicável: cada fusão mostra os sinais que a sustentaram (auditoria);
- barato: regressão logística em ~15 features roda em < 1 s para milhares de pares;
- reversível: flag desliga e volta à regra atual.

### Alternativas rejeitadas (e por quê)

| Alternativa | Motivo |
|---|---|
| Embeddings como decisão | já causou uma história com 645 coberturas (over-merge) |
| LLM por par em produção | custo/latência/não-determinismo; o CI roda a cada 30 min |
| Subir o limiar de cosseno | colapsa recall: pares legítimos de títulos curtos ficam em 0,3–0,4 |
| Clusterização por comunidade (DBSCAN/Louvain) | resolve o grafo, não o par: o erro continua na aresta |
| Só stoplist de palavras | infinito: sempre aparece um novo tema genérico (“menor nível”, “eleição”) |

## 0. Revisão (01/11/2026) — convivência com o outro plano em curso

O outro plano em execução é **C-3 híbrido (scorer história×longform, opt-in via
`--embed`) + A-9 (enquadramento comparado)**. Este plano atua em **artigo×artigo**
(cluster). Convivência:

- **Escopos disjuntos:** `tests/longform_pairs.jsonl` (C-3, 120 pares) ≠
  `tests/cluster_pairs.jsonl` (novo, F1). Não renomear nem mesclar.
- **Artefatos disjuntos:** scorer longform (se integrado) ≠ `state/pair_model.json`
  (F2, cluster). Limiares independentes (0,70–0,75 no longform/internacional;
  τ calibrado do zero aqui).
- **Único compartilhamento:** backend `embed_matrix` e `entities()`. Nenhuma
  mudança neste plano pode alterar o comportamento do `--embed` nas conexões.
- **Ordem:** F0 (instrumentação, opt-in) + F1 (rotulagem) rodam em paralelo agora;
  F2 (treino) só depois da decisão do C-3 híbrido, para não calibrar dois modelos
  sobre embeddings ao mesmo tempo; F3 (flag `--pair-model`) por último.
- **Restrições herdadas:** schema de `data.json` aditivo; CI < 10 min; auditoria
  desligada por padrão (não pode atrasar testes nem rodadas); `state/audit/`
  nunca versionado.

Ajustes aplicados às fases abaixo: F0 opt-in via `audit_path`/env; F1 começa com
seed de 150–200 pares e expande; F2 inferência só-numpy em `app.py`.

## 4. Fases

Cada fase termina com critério de aceite e commit próprio. Não avance sem o aceite.

### F0 — Instrumentação (½ dia) — ✅ feito (01/11/2026)

- [x] `cluster(..., audit_path=None)` opt-in (env `BALANCO_AUDIT` como
      alternativa) em `app.py`; sem `audit_path`, clustering byte-idêntico
      (validado: 5.052 artigos → 3.564 grupos, 0,4 s com e sem audit).
- [x] `ops/audit_pairs.py` (`--run … --top 30`). Primeira rodada real: 4.785
      pares candidatos (3.400 fundidos, 1.385 rejeitados).
- [x] `state/audit/` no `.gitignore`; teste de não-regressão em
      `tests/test_matching.py` (124 testes).
- [x] Seed inicial do F1: `tests/cluster_pairs_seed.jsonl` (16 pares:
      6 same / 2 related / 8 different) a partir das regressões + audit.

- [ ] Em `app.py`, `cluster(..., audit_path=None)` opt-in (env `BALANCO_AUDIT`
      como alternativa): registrar cada par **candidato** (cos ≥ thresh ou
      Se ≥ 0,70) em `state/audit/pairs-<run_id>.jsonl`:
      `{a, b, source_a, source_b, section_a, section_b, dt_h, cos, cos_emb,
      shared, ents, decision, rule}`.
      `decision` ∈ {`fused`, `rejected`}; `rule` = estágio que decidiu
      (`low_sim`, `near_dup`, `no_entity`, `no_content`, `same_source`,
      `time_window`, `fused`). Sem `audit_path`, o clustering é byte-idêntico.
- [ ] `ops/audit_pairs.py`: imprime os 30 pares fundidos menos similares e
      os 30 rejeitados mais similares (para revisão manual).
- [ ] Não versionar `state/audit/` (gitignore).

**Aceite:** uma rodada real gera o arquivo; é possível reconstruir por que cada
história grande tem os membros que tem.

### F1 — Conjunto rotulado (1–2 dias) — ✅ seed concluído (01/11/2026)

- [x] `tests/cluster_pairs.jsonl`: **154 pares** (83 same / 36 related / 35
      different); 138 do audit F0 estratificado + 16 seed manual.
- [x] Medição da regra atual no corpus fixo: different separam 27/27+8/8
      (35/35, precisão 100% no harness); same fundem 27/83 — 56 FNs conhecidos,
      a maioria duplicatas idênticas barradas pela regra `same_source`
      (série da casa) e títulos só-entidade barrados por `no_content`.
- [x] `tests/test_cluster_pairs.py`: different estrito + MUST_FUSE (27) estrito
      + 56 KNOWN_FN como xfail explícito (alvo do F2/F3).

Seed primeiro, expansão depois: começar com **150–200 pares** (regressões já
existentes em `tests/test_matching.py` + top do `ops/audit_pairs.py` — seed de
16 em `tests/cluster_pairs_seed.jsonl`), expandir
para 600–900 na sequência. Formato e amostragem:

- [ ] `tests/cluster_pairs.jsonl`, 3 rótulos:
      `same` (mesmo fato), `related` (mesmo tema/desdobramento, não o mesmo fato),
      `different` (assuntos distintos).
- [ ] Amostragem estratificada por dia (não por rodada), para evitar vazamento:
      - 40% pares fundidos (positivos reais e falsos positivos);
      - 30% pares com cosseno 0,30–0,45 (zona de dúvida);
      - 30% negativos difíceis (mesma entidade, temas diferentes; mesmo tema, entidades distintas).
- [ ] Esquema:
      `{"a": "...", "b": "...", "label": "same|related|different", "source_a": "...", "source_b": "...", "section_a": "...", "section_b": "...", "dt_h": 12.5, "cos": 0.41, "note": "por quê"}`
- [ ] Regra de rotulagem: `same` exige o **mesmo acontecimento** (mesmo ator, mesmo
      ato, mesma janela); desdobramento posterior (retomada de saques depois do
      ataque) é `related`.
- [ ] Dividir em `train`/`test` **por data** (`ops/eval_pair_model.py --split date`).

**Aceite:** seed de ≥ 150 pares (expansão a ≥ 600), ≥ 25% de negativos difíceis, distribuição de rótulos
documentada no cabeçalho do arquivo.

### F2 — Features + modelo (1 dia)

**Preparo concluído (01/11/2026):** `ops/pair_features.py` com vetor fixo de 19
features (`--pairs … --out … [--embed]`; sem `--embed`, `cos_emb = -1`).
Determinístico (duas rodadas byte-idênticas) e com teste em
`tests/test_cluster_pairs.py`. Sinal visível: `shared_spec` médio 3,86 (same)
vs 2,26 (different); o FN c076 carrega `numbers_match=1, subject_match=1`.

**Treino bloqueado até a decisão do C-3 híbrido** (revisão §0).

- [ ] `ops/pair_features.py` com vetor fixo e determinístico:
      `cos_tfidf, cos_emb, jaccard, cov_short, cov_rep, shared_all, shared_spec,
      shared_multi, shared_numbers, same_number, same_section, same_group,
      dt_hours, len_a, len_b, ent_in_first3_a, ent_in_first3_b, subject_match`.
- [ ] Treinar `LogisticRegression` (L2) ou `HistGradientBoosting`, com
      `class_weight="balanced"`; salvar em `state/pair_model.json`
      (coeficientes + nomes das features + limiar, sem pickle).
      **sklearn só em `ops/`; `app.py` usa inferência só-numpy a partir do JSON.**
- [ ] Escolher o limiar por **precisão ≥ 0,97** na classe `same` (curva PR), e
      reportar o recall correspondente.
- [ ] `ops/eval_pair_model.py`: P/R/F1 por rótulo, matriz de confusão e os 20 erros
      mais confiantes (para revisão).

**Aceite:** no split de teste, P ≥ 0,97 em `same`, com recall ≥ 0,80; nenhum par
`different` com probabilidade ≥ 0,5.

### F3 — Integração e A/B (1 dia)

- [ ] Flag `--pair-model CAMINHO` (ou env `PAIR_MODEL`). Sem o arquivo, o
      comportamento atual permanece idêntico (fallback obrigatório).
- [ ] Em `_pair_ok`, quando o modelo existir: fundir se `prob ≥ τ` **ou**
      quase-duplicata (`shared ≥ 4` e cobertura ≥ 0,5 ou `cos ≥ 0,62`).
      Manter janela temporal e regra de mesma fonte.
- [ ] Aplicar o modelo também na **coerência**: membro só fica no grupo se
      `prob(membro, medoide) ≥ τ - 0,10`; senão vira grupo próprio.
- [ ] Rodar 3 coletas: (a) regra atual, (b) modelo, (c) modelo sem embeddings.
      Comparar nº de histórias, maior história, cobertura total e 1.685 artigos
      da amostra.
- [ ] Relatório `ops/ab_pair_model.md` com a tabela.

**Aceite:** nenhuma história > 60 coberturas sem revisão; total de histórias entre
-10% e +5% da regra atual; zero mistura de assuntos nos 20 maiores.

### F4 — Avaliação no nível da história (1 dia)

- [ ] Rotular 40 histórias (as 20 maiores + 20 sorteadas) como `pura` ou `misturada`.
- [ ] Medir: % de histórias misturadas, % de cobertura perdida vs. regra atual,
      e “pureza da manchete” (a manchete pertence a todos os membros?).

**Aceite:** ≤ 2% de histórias misturadas (baseline atual ~4,6% de artigos
suspeitos) e perda de cobertura ≤ 5%.

### F5 — Monitoramento (contínuo)

- [ ] No CI, guardar `state/audit/pairs-*.jsonl` como artefato do run.
- [ ] Alerta (annotation) se: história com > 60 coberturas, ou > 8% dos artigos com
      `prob < τ` dentro de histórias.
- [ ] Revisão semanal: `ops/audit_pairs.py --days 7` e re-treino trimestral do modelo
      com os erros encontrados (o conjunto cresce, o limiar é recalculado).

## 5. Arquivos e comandos

| Arquivo | Papel |
|---|---|
| `app.py` | `cluster`, `_pair_ok`, `_cohere`, `attach_hubs` |
| `ops/pair_features.py` | extração de features (novo) |
| `ops/eval_pair_model.py` | treino, calibração, P/R (novo) |
| `ops/audit_pairs.py` | revisão dos pares fundidos/rejeitados (novo) |
| `tests/cluster_pairs.jsonl` | conjunto rotulado (novo) |
| `tests/test_cluster_pairs.py` | portão de CI (novo) |
| `state/pair_model.json` | modelo publicado (não versionado) |

```bash
python ops/eval_pair_model.py --pairs tests/cluster_pairs.jsonl --split date
python ops/audit_pairs.py --run state/audit/pairs-<run_id>.jsonl --top 30
python app.py --body --body-cap 40 --embed --pair-model state/pair_model.json
python -m pytest tests/ -q
```

## 6. Portão de CI

Em `tests/test_cluster_pairs.py`, travar o comportamento atual (fallback) e o
modelo quando presente:

- pares do conjunto que **não** podem fundir (Bulgária × Flávio, Papa vota × Papa
  paz, Mato Grosso soja × TCE) → `cluster` devolve grupos separados;
- pares que **devem** fundir (mesma eleição búlgara, mesmo ataque à Binance) →
  mesmo grupo;
- sem `--pair-model`, o resultado é idêntico ao de hoje (snapshot).

## 7. Riscos e rollback

| Risco | Mitigação |
|---|---|
| Viés de anotador único | amostra dupla de 10% revisada; documentar divergências |
| Vazamento train/test | split por data, nunca por par |
| Modelo velho (notícias mudam) | re-treino trimestral + alerta de deriva |
| Latência no CI | features vetorizadas; teto de 60 s para o gate |
| Regressão silenciosa | flag desliga o modelo; portão de CI com casos reais |

Rollback: remover `--pair-model` do workflow — a regra heurística atual volta a
valer sem mudança de dados.

## 8. Quick wins já aplicados (não repetir)

- Âncora de entidade + conteúdo além do nome em `_pair_ok`.
- Hub exige entidade na manchete e em ≥2 títulos; alias só pelo prenome.
- `HUB_STOP_GEO`: estado/cidade não é pauta.
- “Aprofunde-se”, “Lá fora” e “Outros ângulos” recolhidos na UI.
