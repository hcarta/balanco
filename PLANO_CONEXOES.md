# Plano — Precisão das conexões entre fontes

> Auditoria de 31/10/2026 sobre `docs/data.json` (104 histórias, 36 fontes, 44 longreads, 9 internacional). Cada problema abaixo foi **medido**, não suposto.

## O que a auditoria encontrou

| Conexão | Estado medido | Problema |
|---|---|---|
| **Agrupamento** (notícia = notícia) | P=0.96/R=0.63 no eval | 69 das 104 histórias têm só 2 coberturas; os 18 docs sobre Flávio Bolsonaro das últimas 48h viraram **18 grupos distintos** — o mesmo fato explode em dezenas de mini-histórias |
| **Aprofunde-se** (notícia → longform) | 44 conexões: 14 são da mesma história, 30 de tópico | (a) 1/3 é redundante (a fonte já cobre a história); (b) 6 peças repetidas para múltiplas histórias (uma peça do Nexo sugerida 8×); (c) 2 falsos positivos ("Oeste Sem Filtro", "Palavras Cruzadas") |
| **Lá fora** (notícia → internacional) | 9 conexões | Baixo recall (só 8/104 histórias); matcher por entidades não resolve títulos BR vs EN sem nome próprio em comum |
| **Checagens** (notícia → veredito) | 0 matches hoje | Corpus de 700 é recente demais; matching léxico com guard-rails rígidos |
| **Equivalência** (viés entre fontes) | Viés fixo por fonte | Sem problema novo — mas 14/44 "aprofundamentos" revelam que o agrupador trata longform como cobertura comum |

**Diagnóstico-raiz:** as quatro conexões usam **sinais independentes** (tokens TF-IDF, entidades, vereditos) e cada uma decide sozinha. Um conector semântico único, calibrado num conjunto rotulado, falta.

## Plano em 4 frentes (ordem por impacto)

### F1. Conector semântico unificado (prioridade máxima)
Hoje: 3 matchers (TF-IDF para cluster, `claim_overlap` para checagens, `entity_match` para longform/intl) com limiares calibrados à mão, cada um com seu vocabulário.

- [ ] **F1.1 Embeddings como sinal base compartilhado.** O modelo multilíngue já baixa (`--embed`, MiniLM 384d) e passa no eval (P=0.90/R=0.70). Unificar: `sim(doc_a, doc_b)` retorna cosseno de embeddings + tokens + entidades em um score só, usado pelas 4 conexões com pesos por tipo.
- [ ] **F1.2 Conjunto rotulado por conexão** (extensão do eval existente): +60 pares notícia↔longform ("é aprofundamento?"), +40 notícia↔internacional ("é a mesma pauta?"), +30 notícia↔checagem. Rotulagem manual sobre amostra estratificada (o script `ops/sample_eval_pairs.py` já faz isso para cluster).
- [ ] **F1.3 Calibração por grade**: rodar os 4 matchers sobre os conjuntos, plotar P/R por limiar (script tipo `ops/compare_embed.py`), escolher o ponto de operação **por conexão** e travar em teste.
- [ ] **Aceite:** cada conexão com precisão medida ≥ 0.9 e recall reportado; regressão quebra o build.

### F2. Consertar o agrupamento (o maior ganho de UX)
18 grupos para um só fato é o problema mais visível: o feed vira pulverização de 2-coberturas.

- [ ] **F2.1 Clustering em 2 estágios**: primeiro o TF-IDF atual (alta precisão), depois um passe de **merge por entidades+embedding** entre centróides de grupos (junta "Fuga de Flávio: Itamaraty convoca" + "Trump ajudou na fuga" + "Dono do avião diz..."). Regra: merge só se 2+ entidades específicas em comum **e** cosseno embedding ≥ 0.55 entre títulos representativos.
- [ ] **F2.2 Janela temporal maior para o mesmo tópico quente**: enquanto um tópico tiver matéria nova < 12h, aceitar irmãos até 7 dias (hoje: 24h para hard news).
- [ ] **F2.3 Mergear no `data.json`, não no cluster**: manter o cluster puro; o merge vira um passo `consolidate(stories)` com regra de **escolha do título representativo** (a história mais coberta absorve as irmãs e lista as demais como "desdobramentos").
- [ ] **Aceite:** Flávio/48h em ≤ 4 grupos; histórias de 2-coberturas caem de 69 para < 40 sem criar nenhum falso merge no eval (P≥0.94 mantido).

### F3. Qualidade do "Aprofunde-se" e "Lá fora"
- [ ] **F3.1 Filtrar não-jornalismo do pool longform**: excluir "assista ao programa", "palavras cruzadas", "quiz", agendas/podcasts por padrão de título (2 falsos positivos medidos).
- [ ] **F3.2 Penalizar redundância**: se a fonte do longform já está entre as coberturas da história (14 casos), só sugerir se a peça for **análise** (título com marcadores: "análise", "por que", "como", "entrevista") — senão omitir.
- [ ] **F3.3 Dediversificação**: máx. 1 sugestão por fonte por história; peça repetida entre histórias só na mais coberta (a do Nexo 8× vira 1).
- [ ] **F3.4 Recall internacional via tradução de âncoras**: dicionário BR↔EN de entidades do dia (Brasil→Brazil, "Banco Central"→"central bank") + aceitar match por **1 entidade multi-palavra forte** (cosseno embedding ≥ 0.6 como segunda evidência). Testar em 40 pares rotulados (F1.2).
- [ ] **Aceite:** zero "programa/quiz" sugeridos; redundância mesma-história < 5%; peça repetida em ≤ 2 histórias.

### F4. Checagens: corpus histórico + recall
0 matches em 104 histórias é subaproveitamento do diferencial do produto.

- [ ] **F4.1 Lupa completa** (5.753 itens): coletar em lote uma vez (script `ops/backfill_lupa.py`), guardar em SQLite e usar por janela de 30 dias por rodada.
- [ ] **F4.2 Matching híbrido**: entidades específicas OU `claim_overlap` atual OU embedding ≥ 0.6 (o mesmo conector de F1) — hoje só o léxico com raro-termo decide.
- [ ] **F4.3 Selo "não checado ≠ verdadeiro"**: manter o botão "verificar tema" em toda história sem match (já existe) e medir taxa de cliques via `data.json` quando houver analytics.
- [ ] **Aceite:** em dia de pauta política quente, ≥ 30% das histórias com selo ou botão relevante; FP=0 em 30 pares rotulados.

## Ordem de execução e esforço

| Ordem | Frente | Esforço | Ganho |
|---|---|---|---|
| 1 | F3.1–F3.3 (filtros/dedup no aprofunde-se) | 1 sessão | Remove os erros visíveis já medidos |
| 2 | F2 (consolidação em 2 estágios) | 2 sessões | Feed deixa de ser pulverização |
| 3 | F1 (conector unificado + rotulagem) | 3 sessões | Base calibrada para todas as conexões |
| 4 | F4 (corpus Lupa + híbrido) | 2 sessões | O diferencial anti-desinfo acende |
| 5 | F3.4 (internacional) | 1 sessão | Depende do conector de F1 |

Total: ~9 sessões. F3 primeiro porque os falsos positivos já estão medidos e a correção é barata; F1 é o investimento estrutural que deprecia calibração manual em todas as frentes.

## Riscos

- **Embeddings no CI**: modelo de 470MB não roda no Actions; portões do eval ficam no TF-IDF puro e o híbrido roda local (`ops/` fora do CI).
- **Over-merge em F2**: mitigado pelo eval de 100 pares + regra de entidades específicas; merge nunca automático entre fontes da mesma editoria.
- **Rotulagem subjetiva** (F1.2): pares discordantes (≥ 2 rotulações divergentes) entram como "borderline" e não contam para o portão.
