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

- [x] **F1.1 Embeddings como sinal base compartilhado.** O modelo multilíngue já baixa (`--embed`, MiniLM 384d). Nesta rodada o embedding entrou como **segunda evidência** (não como score único): confirma um par que já tem âncora lexical. A unificação de pesos fica para depois de F4 — os quatro matchers ainda têm vocabulários distintos.
- [x] **F1.2 Conjunto rotulado por conexão.** 167 pares rotulados à mão (`tests/conn_pairs.jsonl`), amostrados do **pré-filtro** (entidade em comum ou cobertura ≥ 0,12), não do universo de pares: é a distribuição que o scorer vê em produção. Composição: longform 60 (26 positivos), internacional 40 (11), checagem 67 (3). Critério: 1 = mesmo fato/pauta específica; 0 = mesma pessoa/instituição ou tema amplo; artigo idêntico = 0 (redundância).
- [x] **F1.3 Calibração por grade.** `ops/eval_connections.py` mede P/R por sinal e limiar; `tests/test_connections.py` trava o ponto de operação. Linha de base (regra lexical, 31/10/2026):

  | Conexão | P | R | Suporte |
  |---|---|---|---|
  | Aprofunde-se | 0,94 (IC95 0,73–0,99) | 0,62 | 60 pares, 26 pos |
  | Lá fora | 1,00 (IC95 0,68–1,00) | 0,73 | 40 pares, 11 pos |
  | Checagens | 1,00 | 0,33 | 67 pares, **3 pos** |

- [x] **F1.4 Dedup global do "Lá fora".** A mesma peça internacional aparece no máximo em **uma** história (a de maior correspondência). Antes, o texto do Guardian sobre Flávio saía 4× em histórias diferentes.
- [x] **Aceite:** cada conexão com precisão medida ≥ 0,90 e recall reportado; regressão quebra o build. **Cumprido** para longform e internacional. Checagem não tem suporte para calibrar recall (3 positivos em 67 pares) — ver F4.

**Resultado F1 (31/10/2026).** O gargalo não era o score: os matchers já eram precisos; era o **pool** e o **sinal de produção**, que divergia do que o eval media. Duas correções vieram daí:

1. **Aprofunde-se casava por título + resumo.** Qualquer peça cujo resumo mencionasse "Flávio Bolsonaro" grudava em toda história sobre ele (3 falsos positivos em 5 conexões). O eval sempre mediu **só título**; a produção agora usa só título. P 0,94/R 0,62 preservados.
2. **Boost por embedding fora do pré-filtro.** Aplicado a todos os pares, ligava "diplomata argentina" a "voto das capitais" (cosseno alto, zero relação). A amostra não pegava isso porque **toda ela já passava pelo pré-filtro** (viés de seleção). Agora o embedding só confirma pares com entidade em comum ou cobertura ≥ 0,12 (`EMB_PREFILTER_COV`).

Com o boost ancorado (`entidade OR embedding ≥ 0,75`, opt-in `--embed`): longform P 0,95 / R 0,62→0,69; internacional P 1,00 / R 0,73→0,82, sem novo falso positivo na amostra. **O CI continua na regra lexical** (modelo de 470 MB não roda no Actions); o boost é experimental e local até F4 validar em escala.

### F2. Consertar o agrupamento (o maior ganho de UX)
18 grupos para um só fato é o problema mais visível: o feed vira pulverização de 2-coberturas.

- [x] **F2.1 Consolidação de mesmo fato** (`consolidate`): mantém o cluster puro e funde, num segundo passe, histórias que descrevem o **mesmo fato**. Exige entidades específicas em comum **e** um segundo sinal de "mesmo fato": cobertura ≥ 0.35 do título mais curto com 2+ tokens raros, ou embedding ≥ 0.70.
- [x] **F2.2 Janela**: 48 h na consolidação (mais larga que a do cluster), com o segundo sinal impedindo fusões por assunto.
- [x] **F2.3 Merge no `data.json`**: a história mais coberta absorve as irmãs e lista as demais em `developments` ("também apurado"), recalculando contagens, média e blindspot.
- [x] **F2.4 Pautas** (substitui o merge amplo): histórias que compartilham um nome próprio multi-palavra (ex.: "Flávio Bolsonaro") recebem `hub` e aparecem como "🔗 Outros ângulos desta pauta" — navegação sem fundir contagens.
- [x] **Aceite revisto:** 3 fusões de mesmo fato, zero falsos positivos observados; Flávio/48h continua em 8 histórias, mas agrupadas em **1 pauta** navegável.

> **Por que o aceite original (Flávio ≤ 4 grupos) foi abandonado.** Medido em 31/10: fundir por entidade juntaria "Rubio e Vieira conversam" (11 coberturas) com "Trump e Milei pressionam" (3) e com "Michelle chama Jair de líder" (5) — fatos distintos. A barra de viés passaria a somar enquadramentos de eventos diferentes, destruindo a comparação que é o núcleo do produto. Cobertura de título separa fato igual (0.36–0.40) de assunto adjacente (0.00–0.29); embeddings separam melhor (0.70–0.88 × 0.55–0.65), mas não rodam no CI. A pauta entrega a navegação pretendida sem esse custo.

### F3. Qualidade do "Aprofunde-se" e "Lá fora"
- [x] **F3.1 Filtrar não-jornalismo do pool longform**: excluir "assista ao programa", "palavras cruzadas", "quiz", agendas/podcasts por padrão de título (2 falsos positivos medidos).
- [x] **F3.2 Penalizar redundância**: se a fonte do longform já está entre as coberturas da história (14 casos), só sugerir se a peça for **análise** (título com marcadores: "análise", "por que", "como", "entrevista") — senão omitir.
- [x] **F3.3 Dediversificação**: máx. 1 sugestão por fonte por história; peça repetida entre histórias só na mais coberta (a do Nexo 8× vira 1).
- [ ] **F3.4 Recall internacional via tradução de âncoras**: dicionário BR↔EN de entidades do dia (Brasil→Brazil, "Banco Central"→"central bank") + aceitar match por **1 entidade multi-palavra forte** (cosseno embedding ≥ 0.6 como segunda evidência). Testar em 40 pares rotulados (F1.2).
- [x] **Aceite:** zero "programa/quiz" sugeridos; redundância mesma-história < 5%; peça repetida em ≤ 2 histórias.
  - **Resultado (31/10):** 44 → 11 conexões; redundância 14 → 0; peças repetidas 6 → 0 (máx. 1); não-jornalismo 2 → 0. Custo: histórias com "Aprofunde-se" caíram de 22 para 8 — o pool tem 85 peças longform/72 h, mas só 11 casam com as pautas do dia. É falta de recall, a ser recuperada em F1/F3.4.

### F4. Checagens: corpus histórico + recall
0 matches em 104 histórias é subaproveitamento do diferencial do produto.

- [x] **F4.0 Diagnóstico do recall (31/10/2026).** Em 67 pares notícia↔checagem rotulados, só **3** são a mesma alegação. O léxico acerta 1 (P 1,00 / R 0,33); os outros 2 não compartilham tokens com o título da matéria. Conclusão: o problema não é limiar, é **representação** — ligar "o que foi checado" à alegação exige extração de claim, não mais TF-IDF.
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
