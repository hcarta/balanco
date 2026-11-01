# PLAN_CLAUDE.md — Revisão do Balanço e plano de implementação

> **Para o agente implementador.** Este documento é autossuficiente. Leia as seções 0 e 1, execute as fases da seção 9 na ordem, e use a seção 2 como linha de base medida.
> Revisão feita em 31/10/2026 sobre o zip `Balanço` (cache de 5.034 artigos, `docs/data.json` com 120 histórias, 75 testes passando, 0 skipped).
> Todos os números abaixo foram **medidos** sobre `docs/data.json` e `state/cache.db` do zip, salvo onde marcado **[não verificado]**.

---

## Revisão 31/10/2026 — depois de F1–F4

> Esta seção foi escrita após a implementação das fases F1–F4 de `PLANO_CONEXOES.md`. O restante do documento continua válido como diagnóstico; onde houver divergência, vale esta revisão.

### Baseline atualizado
- **113 testes, 0 skipped** (não 74/1). O `README.md` foi atualizado.
- 120 histórias · 1.470 artigos · 375 em histórias · 1 com longreads · 7 com world · 0 checagens · 9 hubs · 2 developments · 76 com 2 veículos.
- Conexões medidas: longform P 0,94/R 0,62; internacional P 1,00/R 0,91 (40 pares); checagens P 1,00/R 0,67 (67 pares, corpus realista) — mas **0 matches na rodada**.

### P0 confirmados (ainda abertos)
- **F-01 cap:** O Globo 821→60 (cobre 7,6 h), G1 465→60 (2 h), Folha 236→60 (9,8 h), Valor 678→60 (22 h).
- **F-02 fuso:** `time.mktime` em `collectors.py:178`, `factcheck.py:94` e `:160`; **283 artigos** com `ts > now+5min`.
- F-03 ids posicionais · F-04 single-link · F-06 longform só 72 h (piauí: 31 itens/29 d, 2/72 h) · F-11 CNN (6/72 h, mas os itens são anúncios) · F-12 testes dependem de `data.json` (agora também `test_connections.py`) · F-13 cache com chave fixa e commit de `data.json` a cada 30 min.

### Correções ao plano
1. **F-02, migração:** `published` também está deslocado pelo mesmo `mktime`; recalcular `ts` a partir dele **não corrige**. Refazer a coleta (`--fresh`) ou subtrair o offset local. O teste deve comparar com o `pubDate` bruto, não com `published`.
2. **F-03, âncora:** usar `first_seen`, não `published`, para o id não mudar quando um artigo mais antigo chega atrasado.
3. **F-07:** o payload atual tem **0** summaries `None`; o item da piauí ainda tem `None` no cache. Manter a guarda, mas o número “3” não se reproduz.
4. **F-15:** `classify_llm.py` já é OpenAI-compatível via `LLM_BASE_URL`; `LLM_PROVIDER` não é necessário.
5. **F-08/piauí:** “Vitória da democracia…” (`/web/ft136/`) é tratado como podcast só por inferência (`summary: None`); link e título não provam podcast. Verificar a categoria do feed antes de usar como evidência.
6. **A-8 conflita** com o requisito de “Todas as histórias” (cronológico, depois nº de veículos, tolerância de 1 h). Aplicar o score só ao hero/destaques ou criar uma aba separada.
7. **A-5 conflita** com a decisão atual de não rodar embeddings no CI. Manter o CI lexical; ONNX é experimento com medição, não DoD.
8. **C-6/B-1 incluem fontes pagas** (Atlantic, New Yorker, NYRB, Foreign Affairs). Pela regra do projeto, só RSS/sitemap público; testar termos e excluir o que exigir paywall.

### Escopo e ordem recomendada
O plano de 5 fases × 3–4 dias é maior que o objetivo atual (precisão das conexões, uso pessoal). Ordem:
- **P0 (1–2 dias):** F-02 → F-12 (fixture) → F-01+F-14 juntos (cap 400, não 1.500) → F-03 mínimo → F-13.
- **P1 (2–3 dias):** F-06/C-1 (índice 120 d, incremental) → F-11 → F-07/F-10 → F-05.
- **P2 (3–5 dias):** F-04 (coerência) → A-7 (grupos independentes) → A-8 só no hero.
- **Adiar:** A-2 com 300 entidades (começar com 50), A-4 regressão logística (tentar regra simples antes), A-5 ONNX, A-9, B-4, C-5, novas fontes em massa.

### Status P0 executado (31/10, tarde)
- **F-02:** `calendar.timegm` nos 3 pontos; `ops/migrate_timestamps.py` corrigiu **2.110** linhas; 0 `ts` no futuro; 2 testes de fuso.
- **F-12:** `tests/fixtures/corpus_2026-10-31.json` (120 histórias, 375 matérias, 80 checagens); o portão de checagens lê o fixture, não o `data.json`.
- **F-01/F-14:** cap **900**; cluster vetorizado (0,3 s para 4.616 artigos, antes O(n²)); `kept/in_window` em `health.json` (O Globo 827/825, Valor 666/666, G1 478/429 por causa dos filtros).
- **F-04:** coerência por medoide (`COHERE_MIN/TAU/RECLUSTER`); maior grupo **140→32**; 473 histórias; sem loteria/vídeo no topo.
- **F-03:** IDs `h…` estáveis + `aliases` herdados; 473 IDs únicos; a UI resolve `?story=` antigo.
- **F-13:** cache com `run_id` + `restore-keys`; `git pull --rebase -X ours` antes do push. Publicação migrada para **deploy-pages** (artefato `docs/`), com fallback automático para o commit em `main` enquanto a origem do Pages estiver em “Deploy from branch”. `data.json`/`feed.xml` não são mais versionados a cada rodada; arquivo/health/ledger vão em commit diário e o ledger também no cache. `state/seed.db.gz` cobre cold start quando o cache do Actions vem vazio.
- **F-08:** filtros de vídeo/ao vivo, loteria, Finados e bandeira tarifária.
- **Checagens:** `claim_match` exige entidade multi-palavra específica ou cobertura ≥0,80; os 4 FPs de “linha do tempo”/“Lula” sumiram; P 1,00/R 0,67 no conjunto; **0 matches** na rodada.
- **C-1/C-5 (leituras):** `build_leituras` lê 10 dias do cache (fontes longform), limita 2 por fonte, sanitiza HTML e exclui anexos de reportagem; 8 peças na página própria **📚 Leituras** e no rail, em 2 colunas e com thumb quando o feed oferece imagem. A página resolve a distância no mobile (o rail fica depois de 490+ histórias).
- **C-2/C-3 (Aprofunde-se):** índice de 120 dias no pool; duas relações — “same” (até 14 dias, regra de entidade atual) e “background” (15–120 dias, exige 2+ entidades específicas distintas e cobertura ≥ 0,20); 1 por fonte, 3 por história, dedup global. UI mostra a relação e as entidades em comum. Nesta edição: 7 sugestões “same” e 0 “background” (o feed da piauí veio com dek curto; o background só entra com 2+ entidades e cobertura ≥0,30).
- **Hub: lugar não é pauta:** `HUB_STOP_GEO` bloqueia estados e cidades como chave (“Mato Grosso” juntava violência em MS, soja e TCE). Pautas no feed: só “Flávio Bolsonaro”.
- **Plano de falsas equivalências:** `PLAN_FALSAS_EQUIVALENCIAS.md` — gate de par aprendido sobre candidatos lexicais (F0 instrumentação → F1 conjunto rotulado → F2 modelo → F3 A/B → F4 avaliação de cluster → F5 monitoramento).
- **Hub com entidade central:** `attach_hubs` só aceita o nome próprio se ele estiver na manchete e em ≥2 títulos da história; alias só pelo prenome. Pautas caíram de 34 para 15 histórias, sem casos como "Democratas cobram Trump" na pauta "Flávio Bolsonaro". UI: Aprofunde-se, Lá fora e Outros ângulos viraram `<details>` recolhidos, com contador.
- **Cluster com âncora de entidade:** par só funde com nome próprio específico em comum **e** conteúdo além das entidades, ou quase-duplicata (4+ tokens, cobertura ≥0,50, S ≥0,62). Tema genérico ("eleição presidencial") não funde fatos distintos — corrigiu o caso Bulgária × Flávio Bolsonaro. Efeito colateral medido: ~10% das histórias antigas eram fusões erradas (acidentes diferentes, "menor nível" de Nasdaq × desemprego) e agora aparecem separadas.
- **Filtro de serviço:** além de loteria/horóscopo, exclui previsão do tempo, alerta meteorológico e calendário de pagamento/benefício (`Calendário do Bolsa Família`, `datas de pagamento do INSS`, `FGTS`), com exceção de evento com impacto real. O passo de commit diário no Actions usa autostash + retry e não derruba o run.
- **A-6:** tabelas `stories`, `story_members`, `story_alias` e `story_events` no SQLite; sync por sobreposição de links; aliases persistem entre rodadas; timeline “quem deu primeiro” por `published` (fallback `first_seen`) no painel. Histórico de merge/split registrado. O `updated` usa só cobertura (opinião/vídeo não rejuvenesce) e a manchete prefere a cobertura das últimas 24 h. Painel de comparação agrupa por veículo com “Mais artigos deste veículo”.
- **A-5:** backend **ONNX/fastembed** (`requirements-embed.txt`, MiniLM multilíngue 384d, ~220 MB, sem torch), modelo em `state/models` cacheado pelo Actions; CI roda `--embed` (conexões longform/internacional), com fallback lexical. O cluster continua lexical; `--embed-cluster` é experimental (a versão anterior criou uma história com 645 coberturas). **113 testes**.
- **C-3 híbrido integrado (decisão 01/11/2026):** `attach_longreads` sob `--embed` admite por `longform_emb_score` (0,45 emb + 0,30 ent-idf + 0,10 rec + 0,10 quality + 0,05 cov) com limiares do eval (same 0,55 / rel 0,45), mantendo âncora lexical (`EMB_PREFILTER_COV`) e todos os guardrails (distinct/cov, F3.2/F3.3); ranking por emb_score. Sem `--embed`, fallback idêntico. Rodada real: 11 histórias com Aprofunde-se (antes 5–7). **130 testes**.
- **B-2/B-3 (Lá fora):** `group_intl_articles` combina cluster + entidade/número; `attach_world` passa a ligar **grupos** (peça representante, `n_sources`, lista de fontes); léxico de conceitos PT/EN aplicado a entidades fortes (marca, lugar ou 2+ entidades; pessoa isolada não ancora). Conjunto internacional: **P 1,00 / R 0,91** (40 pares). **108 testes**.
- **F-11:** CNN International removida (o feed servia anúncios de empréstimo); **New York Times (Tecnologia)** adicionado. 36 fontes.
- **F-10:** `section_label` virou whitelist; “Geral”, “Pt-br”, siglas de UF e editorias desconhecidas não viram mais filtro.
- **Lá fora / Binance:** número do evento (US$ 6,3 bi) + entidade passou a valer; “Binance” × NYT Technology entrou (P 1,00/R 0,91 do conjunto mantidos). A URL de análise citada aparece na história irmã do Bitcoin; a principal mostra outra peça do NYT.
- **Blindspot:** piso baixado para **3+ coberturas** (caso França: 1 L / 2 C / 0 R → blindspot de direita). Só-centro e histórias de 2 veículos continuam `None`; na rodada, 102 blindspots (57 esquerda, 45 direita).
- **F-05:** título representante por **medoide** (similaridade média com as demais manchetes), com `rep_score` só como desempate; sufixos de veículo e marcadores de vídeo removidos.
- **A-7:** grupos editoriais independentes em `sources.yaml` — Globo (G1/O Globo/Valor), BBC (Brasil/World) e NYT (World/Tecnologia). `counts.independent`/`counts.groups`; barra e blindspot usam grupos; a UI mostra “coberturas · grupos”. Histórias de um só grupo não entram.
- **A-3:** `piece_kind` por URL/título/editoria/fonte (hard_news, analysis, explainer, opinion, longform, interview, podcast, video, live, service, fact_check). Só hard_news/analysis/explainer contam na barra/blindspot; os demais ficam no painel como **enquadramento** (`counts.frames`) e são marcados na UI. **101 testes**.
- **Custo:** `data.json` 1,4 MB; arquivo diário slim 717 KB (antes 1,4 MB); rodada ~125 s.
- **Suíte:** **90 testes**.

### Melhorias pontuais
- **F-01:** cap 400 + log `kept/in_window`; medir tempo antes de subir para 1.500.
- **F-14:** `np.argwhere(np.triu(S>=τ,1))` + máscara temporal + tokens; o `S` já existe.
- **F-12:** fixture com stories/articles/factchecks; usar em `test_eval.py` e `test_connections.py`; não ler `docs/data.json`.
- **A-2:** começar com 50 entidades canônicas e IDF; medir nos 167 pares.
- **A-4:** regra simples de coerência primeiro; LR só se não atingir o portão, com validação cruzada.
- **A-7:** `group` + `counts.independent`; recalibrar o blindspot (`tot>=4`).
- **C-1:** índice persistente e incremental; fallback para o feed; não buscar 120 d por rodada.
- **F-13:** `pages: write` + `id-token: write`, `git pull --rebase`, podar caches.
- **§7:** registrar F4.2 (P 1,00/R 0,67; 0 matches/dia) e que o próximo salto é **extração de alegação**.

---

## 0. Contexto e regras do jogo

**O que é o Balanço:** agregador de notícias BR (estilo Ground.news). `sources.yaml` → `collectors.py` (RSS/sitemap) → `store.py` (SQLite) → `app.py` (cluster TF-IDF → consolidação → pautas → longreads → "Lá fora" → checagens) → `docs/data.json` → `docs/index.html` (estático). Roda a cada 30 min no GitHub Actions.

**Comandos úteis**
```bash
pip install -r requirements.txt            # feedparser, pyyaml, requests, numpy, pytest
python -m pytest tests -q                  # baseline: 75 passed, 0 skipped
python app.py --fresh                      # sem cache
python app.py --body --body-cap 40         # como o CI roda
python ops/eval_connections.py             # P/R por conexão
```
> Atenção: o caminho do zip tem `ç` em NFD (macOS). Se `cd Balanço` falhar, use glob (`cd Balan*`).

**Regras (não negociáveis)**
1. **Não quebrar os 75 testes.** Quando um teste codificar comportamento que este plano muda de propósito, atualize o teste *e* registre o motivo no PR/commit.
2. **Schema de `data.json` é aditivo.** `docs/index.html` e `feed.xml` consomem `id, title, summary, counts, pct, articles[], longreads[], world[], checks[], hub, developments, leituras`. Adicione campos; só remova depois de migrar a UI.
3. **Sem bypass de paywall, sem scraping novo.** Fontes novas só via RSS/sitemap/API pública. Metadados de longform vêm do **próprio feed** (`content:encoded`, `category`, `dc:creator`) ou da API WP pública. Não use nada de `ref/bypass-paywalls/` (está no zip; já é `.gitignore`; **remova do zip/distribuição**).
4. **Custo zero por artigo por padrão.** LLM só como opt-in (`--llm`), nunca no CI por padrão.
5. **Medir antes de afirmar.** Toda mudança de matching precisa de P/R antes/depois no conjunto rotulado (seção 8). Não calibrar contra o `data.json` mutável do CI (ver F-12).
6. **Precisão antes de recall** no agrupamento: uma fusão errada destrói a barra de viés (núcleo do produto).

---

## 1. Resumo executivo

Os matchers do projeto são cuidadosos e bem testados, mas **o gargalo está antes e depois deles**: nos dados que entram, na forma como grupos são fechados e na identidade que as histórias têm entre rodadas. Em ordem de impacto:

| # | Achado | Impacto |
|---|---|---|
| 1 | **`PER_SOURCE_CAP=60` descarta quase tudo dos veículos de alto volume.** O Globo tem 821 itens em 72 h e só os 8 h mais recentes entram; G1 tem 465 e só <1 h; Valor 22 h; Band 14 h. G1 aparece em apenas 4 artigos de histórias. | Cobertura cruzada artificialmente baixa; 63 % das histórias têm só 2 veículos |
| 2 | **Bug de fuso:** `time.mktime(pp)` trata struct UTC como hora local. Em máquina em UTC-3 os itens ficam ~3 h no futuro (22 fontes, 96 itens só do G1). O cache do zip está contaminado. | Janelas de tempo erradas, ordem errada, mistura de offsets no cache |
| 3 | **IDs de história são posicionais** (`s{gid:03d}`) e mudam a cada rodada. `s000` de 30/10 = "Alcolumbre pauta PEC…"; `s000` de 31/10 = "Segurança pública…". | `?story=sNNN`, `feed.xml` (`guid`) e arquivo diário apontam para histórias diferentes. Sem permalink |
| 4 | **Union-find single-link fecha grupos errados.** 3 das 4 maiores histórias têm intrusos (ver F-04). Título representante escolhido por comprimento, não por centralidade. | Barra de viés contaminada; manchete de capa ruim |
| 5 | **Longform quase nunca aparece:** 1 de 120 histórias tem "Aprofunde-se" (o README fala em 8). Pool de 72 h; piauí tem 31 itens em 29 dias (2 nas últimas 72 h). Casamento só por **título**, e títulos da piauí são crípticos ("O esgrimista", "O usurpador"), enquanto o *dek* é rico. | A funcionalidade pedida (leituras longas, piauí) está praticamente desligada |
| 6 | **A única sugestão da piauí é provavelmente um episódio de podcast** ("Vitória da democracia…", resumo literal `None`). | Falso positivo de "não-jornalismo" |
| 7 | **Internacional:** 6 fontes anglófonas globais, 7/120 histórias com "Lá fora", sem agrupar peças estrangeiras entre si, CNN RSS morto (itens de até 1.800 dias), nenhuma fonte hispânica/latino-americana. | Pouca "conexão com cobertura internacional" |
| 8 | **Equivalência entre fontes é só por título léxico.** Sem stemming, sem normalização de acento, tokens de 2 letras (PF, PT, PL) descartados, números ignorados, sem tabela de entidades canônicas, sem noção de grupo econômico, sindicalização/agência, tipo de peça. | Recall baixo e falsos positivos |
| 9 | **CI:** `actions/cache/save` com chave fixa `balanco-cache` nunca atualiza (caches do Actions são imutáveis por chave); commit de `data.json` (344 KB) a cada 30 min incha o histórico git. | Cache de estado congelado; repo cresce ~16 MB/dia |

**Plano em 5 fases** (seção 9): F0 correções de dados (1–2 dias) → F1 identidade estável + clustering coerente → F2 camada semântica incremental (embeddings cacheados) → F3 longform/piauí → F4 internacional. Avaliação e portões na seção 8.

---

## 2. Evidências (linha de base medida)

```
n_articles = 1470 (≈300 intl)   | em histórias: 375
histórias = 120                 | com 2 veículos: 76 (63 %); dessas, 34 só-centro
com longreads = 1  | world = 7  | checks = 0 | hub = 9 | developments = 2
histórias com mesma fonte 2×: 12
rótulos de editoria vazando: "Geral" 12, "Pt-br" 4, "Pop" 3
```

**Teto por fonte (últimas 72 h, itens no cache → mantidos):** oglobo 821→60 (cobre 8 h) · valor 681→60 (22 h) · band 508→60 (14 h) · g1 465→60 (<1 h) · gazeta 309→60 · folha 236→60 (7 h) · cnnbr 173→60 (3,6 h) · estadao 125→60 (7 h) · metropoles 120→60 (5,7 h).

**Futuro por fuso:** `estadao +2,95 h`, `metropoles +2,91`, `g1 +2,85 (96 itens)`, `folha +2,79`, … (22 fontes RSS; as de sitemap não são afetadas porque parseiam ISO com offset).

**Piauí no cache:** 31 itens / 29 dias; 2 nas últimas 72 h; summaries úteis (ex.: *"Como o ministro André Mendonça transformou dois escândalos de corrupção – o Master e o INSS – em plataforma eleitoral da direita"* para o título *"O instituto de Mendonça"*), mas 3 itens com summary literal `None` (provável podcast).

**Intrusos em histórias reais (clustering):**
- "Segurança pública será pauta central…" (13): inclui Oeste *"EUA renovam Câmara e parte do Senado na próxima terça-feira"* (casou por "próxima terça-feira").
- "Solano Ribeiro…" (12): inclui Gazeta *"O Brasil que Lutero ajudou a construir"*.
- "Rubio e Vieira conversam…" (10): mistura **Vieira×Lavrov** (outro fato, via "Mauro Vieira"+G20) com Vieira×Rubio.
- Representante errado: a história de 10 veículos que dizem "Alcolumbre pauta PEC da Segurança" tem como manchete *"Segurança pública será pauta central no 4º mandato de Lula"* (maior string de fonte de alta factualidade); a de Solano usa a longa do G1 em vez de "Morre Solano Ribeiro…".

**Fusões perdidas:** "Votação antecipada… 48 mi" × "Votos antecipados… 49 milh" (cov 0,40, números descartados pelo `tok`); 6 histórias distintas sobre a fuga de Flávio (só viram `hub`).

**Longform sugerido hoje (3 itens, todos numa história):** Nexo, Intercept e piauí casando por `flávio`/`lula` isolados (`entity_match` aceita `len(spec)>=2` de nomes únicos).

---

## 3. Falhas e bugs (corrigir primeiro) — Fase 0

Cada item: **onde → problema → correção → critério**.

### F-01 · Teto por fonte trunca a janela (P0)
`store.py:22` `PER_SOURCE_CAP = 60`; `app.py:67-68` `store.recent(..., limit=max(per_feed, PER_SOURCE_CAP))`.
- **Problema:** corta por recência, não por relevância. Quem publica 15 itens/h cobre 4 h.
- **Correção:** (a) subir o cap para ~1.500 e fazer o cluster em matriz **esparsa** com blocagem (F-14); (b) enquanto isso, cap por fonte ≥ 400 e `window_h` do cluster diferenciado por editoria já existente; (c) log de `kept/in_window` por fonte em `health.json`.
- **Critério:** `n_in_window == n_kept` para todas as fontes; tempo da rodada < 90 s em CI; nº de veículos distintos por história sobe (relatar mediana antes/depois).

### F-02 · `time.mktime` interpreta UTC como local (P0)
`collectors.py:178`, `factcheck.py:94` e `:160`.
- **Correção:** `calendar.timegm(pp)` (ou `datetime(*pp[:6], tzinfo=utc)`). Clamp defensivo: `ts = min(ts, now + 5 min)`.
- **Migração:** `store.py` — script único que, para linhas com `ts > first_seen_ts + 10 min`, recalcula `ts` a partir de `published`; ou descartar o cache local e usar o do CI.
- **Teste novo:** com `TZ=America/Sao_Paulo` (monkeypatch `time.tzset`), `fetch_rss` sobre um feed fixture com `pubDate` UTC produz o mesmo `ts` que com `TZ=UTC`.

### F-03 · IDs de história instáveis (P0)
`app.py:404` `"id": f"s{gid:03d}"`; consolidação descarta os ids absorvidos.
- **Correção:** ver **A-6 (identidade persistente)**. Mínimo viável imediato: `id = "h" + sha1(min(link para link em artigos))[:8]`, onde o âncora é o **link do artigo mais antigo** da história; ao fundir, o id da maior história sobrevive e os absorvidos entram em `aliases[]` (a UI redireciona `?story=<alias>`).
- **Critério:** em duas rodadas consecutivas, ≥ 95 % das histórias com ≥ 3 artigos em comum mantêm o mesmo `id`; `feed.xml` `guid` estável.

### F-04 · Clusterização single-link produz intrusos (P0)
`app.py:197-256` (`cluster`, union-find).
- **Problema:** um par com `cos≥0,38 & 2 tokens` basta para ligar; cadeias transitivas juntam fatos distintos. Tokens genéricos de calendário ("próxima terça-feira") valem como evidência.
- **Correção:** **A-4 (coerência de cluster)**: após o union-find, validar cada membro contra o **centroide/medoide**; ejetar membros com `sim(medoide) < τ_out` e re-clusterizar os ejetados separadamente. Adicionar stopwords de calendário/tempo (`terça`, `próxima`, `semana`, `hoje`, `ontem`, `após`, `diz`, `afirma`, `veja`, `entenda`, `saiba`).
- **Critério:** os 3 intrusos da seção 2 saem; P do eval de agrupamento ≥ 0,96 mantido; R não cai.

### F-05 · Título representante por comprimento (P1)
`app.py:341-362` `rep_score`.
- **Correção:** escolher o **medoide** (maior similaridade média com os demais títulos da história; usar emb se houver, senão TF-IDF) e só então aplicar as penalidades de clickbait/factualidade como desempate. Normalizar sufixos (`" - Folha"`, `" | G1"`, `"(vídeo)"`, `"AO VIVO"`).
- **Critério:** na história do PEC e na de Solano o representante é um título que ≥ 60 % dos outros veículos "espelham".

### F-06 · Pool de longform só enxerga 72 h e só título (P0 para o objetivo do usuário)
`app.py:788-842`. Ver **Eixo C** inteiro.

### F-07 · Resumo literal `None` e lixo em summaries (P1)
Origem provável: feed da piauí/enrich. Sanitizar em `collectors._clean` e `enrich`: `{"None","null","undefined","", "[…]"}` → `""`; remover "O post … apareceu primeiro em …" (WordPress). Teste com fixture.

### F-08 · Fontes de agência/podcast/vídeo tratadas como cobertura (P1)
Ex.: episódio de podcast da piauí vira "longread". `NON_JOURNALISM` (`app.py:570`) é regex frágil. Ver **A-3 (tipo de peça)**.

### F-09 · `tok` perde sinal (P1)
`app.py:35-40`. (1) `len(w) >= 3` descarta `pf`, `pt`, `pl`, `g7`; (2) números de 2 dígitos (`"48"`, `"49"`) caem no mesmo filtro e nunca servem de evidência; (3) sem normalização de acento ("Polônia/polonês", "Constitucional/constitucional" ok, mas "polonia" sem acento não casa); (4) sem stemming. `STOP` inclui `alta, queda, recuo, lucro` (necessários para distinguir "Ibovespa cai" de "Ibovespa sobe"). 
- **Correção:** NFKC + casefold + remoção de acento para chave de comparação (manter forma original para exibição); permitir siglas de 2 letras de lista branca (`pf pt pl pp stf tse tcu`…); números viram tokens `NUM:48` e entram na lógica de "mesmo fato" com tolerância (|a−b|/max ≤ 5 %); stemmer RSLP/Snowball-PT (`nltk` é pesado; use `snowballstemmer`, ~100 KB, puro Python) **apenas** para a matriz TF-IDF, não para entidades.
- **Critério:** par "Votação antecipada nos EUA tem recorde de 48 mi" × "Votos antecipados batem recorde nos EUA, com mais de 49 milh…" agrupa; sem queda de P.

### F-10 · Taxonomia de editoria vazando (P2)
`app.py:310-338`. "Pt-br" (DW usa `/pt-br/` na URL), "Geral" (12), "Pop". Adicionar `section_map` por fonte em `sources.yaml` e fallback por classificador (A-3). `GENERIC_SECTIONS` em `collectors.py` deve incluir `pt-br`, `br`, `pt`, `portuguese`, `brasil` quando for prefixo de idioma.

### F-11 · CNN International morto (P1)
`sources.yaml` `cnnintl` usa `rss.cnn.com/rss/edition_world.rss` (herdado; itens do cache vão a 1.800 dias, 6 nas últimas 72 h). Testar `edition.cnn.com` atual; se não houver feed vivo, **remover** ou usar Google News RSS `site:`. Adicionar guarda geral: fonte com `last72h < 3` por 3 rodadas → alerta em `health.json`.

### F-12 · Testes dependem de `docs/data.json` mutável (P1)
`tests/test_connections.py:97` lê o `data.json` versionado; o CI o sobrescreve a cada 30 min, então o portão deriva. Congelar `tests/fixtures/corpus_2026-10-31.json` (títulos+summary+source, ~1.500 itens) e apontar os testes para ele.

### F-13 · CI: cache imutável e histórico inchando (P1)
`.github/workflows/collect.yml:33,46`.
- **Cache:** `actions/cache/save` com a mesma `key` falha silenciosamente após a 1ª vez. Use `key: balanco-cache-${{ github.run_id }}` e `restore-keys: balanco-cache-`. **[verificar nos logs do Actions: "Unable to reserve cache with key"]**
- **Git:** mover a publicação para `actions/upload-pages-artifact` + `actions/deploy-pages` (sem commit) *ou* force-push de uma branch órfã `gh-pages` com só `docs/`. Manter no git apenas `state/health.json` e o ledger, a cada N horas.
- **Commit com push sem rebase:** adicione `git pull --rebase` ou concorrência já existente basta; documentar.

### F-14 · Desempenho do cluster (P2)
Laço `for i in range(n): for j in range(i+1, n)` em Python (n≈1.200 hoje; ≈4.000 após F-01 → ~8 M iterações). Vetorizar: `S = X @ X.T` (já existe) → `np.argwhere(np.triu(S >= τ_cand, 1))` e só avaliar os pares candidatos; janela temporal por máscara de `ts`.

### F-15 · Menores
- `build()` ordena `stories` duas vezes (`app.py:424-425`); a primeira é morta.
- `tfidf_matrix` mantém `df>=2` e depois reinsere raras (`:127-133`), comportamento difícil de raciocinar; simplificar com `min_df=1` e peso sublinear.
- `ENTITY_TRANSLATE` mapeia `onu→un` mas `entities()` aplica `ENTITY_ALIAS` antes — verificar colisões (`us`/`usa`/`eua`).
- `archive_snapshot` grava o payload **inteiro** por dia (≈200 KB × 90); gravar só `stories` com ids e links (ou gzip).
- `SITE_URL` fixo `hcarta.github.io/balanco` — mover para `.env`/`sources.yaml`.
- `enrich.py` ignora `robots.txt` por decisão do dono, em contradição com `ESTRATEGIA_AGREGACAO.md` §2 (princípio 5). Recomendo alinhar: respeitar `robots.txt` para HTML de matéria ou documentar a exceção em `README`/`como-lemos.html`. Para o objetivo deste plano **não é necessário** buscar HTML: use o feed.
- `classify_llm.py` é só OpenAI; torná-lo provedor-agnóstico (variável `LLM_PROVIDER`) se for mantido.

---

## 4. Eixo A — Organizar e juntar notícias de veículos diferentes (equivalências)

Objetivo: transformar "pares de títulos parecidos" em um **modelo de equivalência em 4 níveis**, cada um com chave própria e medido.

```
Entidade (Flávio Bolsonaro = "Flávio" = "senador Flávio" = "Flavio Bolsonaro" [EN])
   └─ Artigo (1 URL, 1 veículo, 1 tipo de peça, 1 data)
        └─ Evento / História (mesmo fato; barra de viés; N veículos independentes)
             └─ Pauta (narrativa guarda-chuva; navegação, sem somar contagens)
```

### A-1 · Representação por artigo (nova camada `repr.py`)
Para cada artigo, calcular e **persistir no SQLite** (tabela `features`):
- `norm_title` (sufixos de veículo removidos, NFKC, casefold), `title_tokens` (F-09), `numbers[]`.
- `entities[]` **canônicas** (A-2), com `type` (PER/ORG/LOC/EVENT).
- `emb` = embedding de `title + " — " + dek` (A-5), `float16`, 384 d.
- `kind` (A-3), `section_canon` (F-10), `lang`, `country` (da fonte).
- `dek` = resumo do feed (≥ 40 chars, sanitizado). **Para longform e para fontes sem dek (sitemaps), enriquecer** só via `--body` quando já permitido.
Tabela: `features(link PK, norm_title, tokens, numbers, entities_json, emb BLOB, kind, section_canon, lang, model, ts_feat)`. Recalcular só linhas novas ou com `model` diferente → **custo incremental ≈ 50–150 artigos por rodada**.

### A-2 · Registro de entidades canônicas (`entities.yaml`)
Hoje: `ENTITY_ALIAS` e `ENTITY_TRANSLATE` em `app.py:504-524`, só lugares e 5 aliases. Falta pessoas, instituições e conceitos recorrentes.
```yaml
- id: flavio_bolsonaro
  type: PER
  names: {pt: ["Flávio Bolsonaro","Flávio","senador Flávio"], en: ["Flavio Bolsonaro"], es: ["Flavio Bolsonaro"]}
  generic: false
- id: stf
  type: ORG
  names: {pt: ["STF","Supremo Tribunal Federal","Supremo"], en: ["Brazil's Supreme Court","Supreme Federal Court"], es: ["Corte Suprema de Brasil"]}
- id: banco_central
  type: ORG
  names: {pt: ["Banco Central","BC","Copom"], en: ["Central Bank of Brazil","Brazil's central bank"]}
- id: tarifaco
  type: EVENT
  names: {pt: ["tarifaço","tarifas de Trump"], en: ["Trump tariffs","tariffs on Brazil"]}
```
- Construir **semi-automaticamente**: rodar NER (spaCy `pt_core_news_sm`/`en_core_web_sm`, **offline, apenas local**, resultado commitado em `entities.yaml`) sobre o cache de 5 k artigos, listar entidades por frequência, revisar à mão as ~300 mais frequentes. Reservar `generic: true` para tokens que **não** provam tópico (já há `ENTITY_GENERIC`).
- `entities()` passa a: casar *surface forms* (maior-primeiro, com fronteira de palavra) → ids. Manter fallback atual (capitalizadas) para entidades fora do registro, **com peso menor**.
- **Peso por IDF de entidade** (raridade no corpus da rodada): "Lula" (muito comum) vale pouco; "Oleshky" vale muito. Substitui a regra binária de `entity_match` (`len(spec)>=2`) que hoje liga qualquer par que cite "Flávio" e "Lula".
- **Critério:** os 3 longreads atuais (casados só por `flávio`/`lula`) deixam de passar sozinhos; recall internacional do conjunto rotulado ≥ 0,91 mantido.

### A-3 · Tipo de peça (`kind`) e família de editoria
Taxonomia: `hard_news | analysis | opinion | explainer | interview | longform | video | podcast | live | service | fact_check`.
- Regras (ordem): padrão de URL (`/colunas/`, `/opiniao/`, `/podcast/`, `/video/`, `/ao-vivo/`, `/blogs/`), marcadores de título (`ANALYSIS_MARKERS`, "Entenda", "Por que", "Entrevista", "AO VIVO", "Vídeo:"), default por fonte (`kind_default` em `sources.yaml`: piauí/Pública/Intercept/Repórter Brasil = `longform`), e por último comprimento/dek.
- Usos: (1) **só `hard_news|analysis|explainer` contam como "cobertura"** para a barra e blindspot; opinião e longform entram na história como "enquadramentos", não como veículos de cobertura; (2) podcast/vídeo/live ficam fora do "Aprofunde-se"; (3) filtro na UI.
- Regra de fonte: `kind_default` + `section_map` em `sources.yaml`.

### A-4 · Pipeline de clustering em dois estágios com coerência
Substituir `cluster()` (mantendo assinatura para os testes) por:
1. **Candidatos:** pares com `S_tfidf ≥ τ_c` **ou** `S_emb ≥ τ_e` **e** janela temporal (por `pair_window`, já existente) — vetorizado (F-14).
2. **Pontuação do par** (`pair_score`): combinação calibrada de `[cos_tfidf, cos_emb, jaccard_entidades_ponderado, num_match, Δt_h, mesma_seção_família, mesma_fonte, kind_compat]` por **regressão logística** treinada nos 100+ pares de `tests/eval_pairs.jsonl` (+ novos, seção 8). Gravar os coeficientes em `models/pair_lr.json`; sem sklearn em produção (só `numpy` para inferência; treinar em `ops/train_pair_model.py`).
3. **Agrupamento:** agglomerative **average-linkage** com corte em `τ_link` (ou, equivalente e simples: union-find *apenas* em pares com `score ≥ τ_high`, e ligar `τ_low ≤ score < τ_high` só se ambos os lados já tiverem ≥ 2 vizinhos fortes em comum).
4. **Coerência:** para cada cluster com ≥ 3 itens, calcular medoide; ejetar membros com `sim(medoide) < τ_out`; reprocessar ejetados como sementes.
5. **Mesma fonte 2× no cluster** = "atualização": manter o mais recente como representante do veículo e listar o outro em `articles[].versions[]`; **não** contar 2× na barra.
6. **Fatos vs. assunto:** manter `consolidate()` (F2) — é conservador e foi bem validado; só passar a usar entidades canônicas e o `pair_score`.
- **Critério:** eval de agrupamento (P ≥ 0,96, R ≥ 0,75 — hoje 0,96/0,63, ou 0,90/0,70 com embeddings); zero intrusos nos 4 maiores grupos do corpus congelado; mediana de veículos por história sobe.

### A-5 · Embeddings baratos, incrementais e no CI
O README mede que embeddings melhoram R de 0,63→0,70 mas "não rodam no CI" (torch + MiniLM 470 MB). Resolver:
- **ONNX + `fastembed`** (ou `onnxruntime` + `tokenizers`) com **`paraphrase-multilingual-MiniLM-L12-v2` quantizado** ou **`multilingual-e5-small` int8** (~120 MB). Sem torch. Baixar o modelo no 1º run e guardar em `actions/cache` (chave por versão do modelo). **[não verificado: tamanho/latência no runner; medir]**.
- Persistir vetores em `features.emb`; cada rodada embeda **só itens novos** (~100 × ~15 ms ≈ 2 s).
- Flag `--embed` passa a ser o **padrão no CI** quando o modelo estiver em cache; fallback automático para TF-IDF se falhar. Registrar `model` em `data.json.meta`.
- Reaproveitar a mesma matriz para: cluster (A-4), consolidação, longform (C), internacional (B) — **um só espaço semântico**, como já previa `PLANO_CONEXOES.md` F1.1.

### A-6 · Identidade persistente de histórias (corrige F-03)
Tabelas novas em `store.py`:
```sql
stories(story_id TEXT PK, created TEXT, anchor_link TEXT, status TEXT);   -- active|merged|archived
story_members(story_id TEXT, link TEXT, first_seen TEXT, PRIMARY KEY(story_id, link));
story_alias(alias TEXT PK, story_id TEXT);                                -- ids absorvidos
story_events(ts TEXT, story_id TEXT, kind TEXT, detail TEXT);             -- merge|split|new_member
```
Algoritmo por rodada: após o cluster, casar cada novo grupo com a história anterior de **maior sobreposição de links** (Jaccard ≥ 0,4); herdar `story_id`; se um grupo cobre 2+ histórias → merge (id da maior sobrevive, o resto vira alias); se uma história se parte → split com novo id para a menor parte. UI: `?story=` resolve alias; `feed.xml` usa `story_id`.
- Bônus: dá a **linha do tempo** de cada história (entrada de veículos, `first_seen` por veículo → "quem deu primeiro"), hoje inexistente.
- **Critério:** F-03.

### A-7 · Equivalência entre **fontes** (independência real)
Em `sources.yaml` adicionar campos (todos opcionais, com default):
```yaml
group: globo            # g1, oglobo, valor → "globo"; folha+uol → "folha_uol"? (decidir)
country: BR
lang: pt
kind_default: hard_news
section_map: {"poder": "politica", "pt-br": null}
wire_partners: [estadao_conteudo, agencia_brasil]   # republica texto de agência
```
- **Contagem independente:** `counts.total` (itens) e **novo** `counts.independent` (= nº de `group`s distintos). Barra e blindspot usam `independent`; a UI mostra "11 coberturas · 8 grupos". Evita que G1 + O Globo + Valor (mesmo grupo) valham 3 vozes.
- **Detecção de sindicalização/cópia:** `simhash`/Jaccard de 5-gramas de caracteres sobre `norm_title + dek`; se ≥ 0,85 e fontes com `wire_partners` ou mesmo `group` → marcar `derived_from` e não contar como independente. Também detectar créditos "Agência Brasil/Reuters/AFP/EFE/Lusa" no dek (já em `GENERIC_SECTIONS` como ruído de URL).
- **Fatiar viés por grupo:** a UI deve poder mostrar "Esquerda 2 grupos · Centro 5 · Direita 3".

### A-8 · Ranking da capa
`app.py:424-425` ordena só por nº de coberturas. Trocar por `score = log(1+independent) · recency(h; meia-vida 18 h) · (1 + 0.25·diversidade_L/C/R) · (1 + 0.15·tem_world)`, com `pin` manual opcional. Evita histórias de 3 dias na frente.

### A-9 · Enquadramento comparado (produto)
Dado o agrupamento, mostrar **como cada lado intitulou**: calcular log-odds de tokens por bucket (L/C/R) dentro da história e destacar 2–3 termos distintivos ("fuga" × "viagem"; "golpismo" × "contestação"). Barato (contagens) e é o diferencial natural do Ground. Guardar em `story.framing = {L:[...], C:[...], R:[...]}`.

---

## 5. Eixo B — Conexão com a cobertura internacional

**Estado:** 6 fontes anglófonas "world" (Al Jazeera EN, CNN Intl [morto], Fox, NYT, Guardian, BBC World), 7/120 histórias com "Lá fora", dedup global de peças (bom). Matching por entidade + tradução de 38 lugares.

### B-1 · Ampliar o pool (testar cada endpoint antes de adicionar — protocolo já usado no projeto, registrar em `ESTRATEGIA_AGREGACAO.md`)
Adicionar `country`, `lang`, `region` em cada fonte. **Candidatas [todas não verificadas: testar RSS/sitemap vivo e termos de uso]:**
- **Feeds focados no Brasil/América Latina** (aumentam recall sem ruído): Guardian `/world/brazil/rss`; BBC `news/world/latin_america/rss.xml`; NYT `Americas.xml`; Al Jazeera "Latin America"; AP/Reuters via **Google News RSS** `site:` (padrão já usado em `factcheck.fetch_aosfatos`) quando não houver RSS próprio.
- **Hispano-americanas** (cobrem Argentina/Bolívia/Venezuela, que hoje geram histórias BR como "convoca representante da Argentina"): Clarín, La Nación (AR), Infobae, Página/12, El País América, MercoPress (EN, Mercosul), Buenos Aires Times.
- **Europa/Ásia:** DW English, France 24 / RFI, Le Monde (EN/FR), Japan Times, SCMP, The Hindu, Al-Monitor — para o "contraste de bloco" (EUA × Europa × Sul Global × Oriente Médio).
- **Brasil visto de fora:** Brazilian Report, Americas Quarterly, Mongabay (Amazônia), Rest of World (tech).
- Rotular `bloc` (US/UK/EU/LatAm/MENA/Asia/Africa) para a UI mostrar **diversidade de origem**, não só contagem.
- Remover/trocar CNN Intl (F-11).

### B-2 · Agrupar o internacional **entre si** primeiro
Hoje cada peça estrangeira é casada isoladamente com cada história BR. Fazer o cluster de `intl` por evento (A-4 com embeddings multilíngues) e depois ligar **grupo intl ↔ história BR**. Resultado: "Lá fora" mostra "5 veículos de 4 países cobriram isso" com a mesma barra/lista de propriedade/país, e o dedup global vira trivial.

### B-3 · Casamento multilíngue
Ordem de sinais (todos precisam de pré-filtro lexical/entidade para evitar o falso positivo já medido de embedding sem âncora — `EMB_PREFILTER_COV`):
1. **Entidades canônicas multilíngues** (A-2) — resolve "Supremo"↔"Supreme Court", "Banco Central"↔"central bank", pessoas com grafia diferente.
2. **Embedding multilíngue** de `title + dek` (A-5), limiar calibrado no conjunto rotulado (hoje 0,75 *com* âncora).
3. **Âncoras numéricas e datas** ("500 mísseis Patriot", "70 mil policiais").
4. **Léxico de conceitos** BR↔EN para temas recorrentes sem nome próprio (tarifa/tariff, eleição/election, juros/interest rates, protestos/protests, Ebola…) — pequena tabela em `entities.yaml` (`type: CONCEPT`) alimentada pelos pares rotulados que falham.
- Meta: recall internacional ≥ 0,85 em ≥ 150 pares (hoje 0,91 em **40 pares/11 positivos**: IC enorme; ampliar o conjunto é pré-requisito).

### B-4 · Produto: três vistas simétricas
1. **Lá fora** (já existe): enquadramento estrangeiro de uma história BR — adicionar país, bloco, viés da fonte e, quando houver ≥ 2 peças, "como o exterior lê vs. como o Brasil lê" (termos distintivos, A-9).
2. **Só lá fora (blindspot internacional):** grandes histórias do exterior **sem** equivalente BR (peças intl que mencionam entidades do Brasil/Mercosul mas não casam com história BR; ou clusters intl com ≥ 3 países e 0 BR). Seção "O que o Brasil não está vendo".
3. **Brasil visto de fora:** peças estrangeiras *sobre* o Brasil (entidade BR em ≥ 1 título), ordenadas por alcance, mesmo que a história BR correspondente não exista.
- UI: `world` ganha `country`, `bloc`, `lang`, `bias`, `ownership`; link sempre para o original; não traduzir/republicar texto (só título + link; tradução de título opcional e **marcada como automática**, via modelo local; **[decisão do dono]**).

---

## 6. Eixo C — Sugestão de leituras longas (revista piauí e outras)

### Diagnóstico
- O pipeline procura longform **dentro das últimas 72 h** (`fetch_all` → `store.recent`). A piauí publica ~1 peça/dia útil em média (31 em 29 dias) e muitas são ensaios, perfis e reportagens com **vida de semanas**. Resultado medido: 1 história com longread.
- Casamento **só por título** (decisão de `PLANO_CONEXOES.md` F1 para evitar FP). Mas o problema era o **scorer** (entidade isolada aceita) e não o uso do dek: os deks da piauí são ricos em entidades ("Master", "INSS", "André Mendonça").
- Nenhum metadado de leitura: autor, editoria, tempo de leitura, tipo.
- Misturam-se podcast/newsletter ("Foro de Teresina") com texto.

### C-1 · Índice persistente de longform (`longform_index`)
- Tabela `longform(link PK, source_id, title, dek, authors, categories, published, reading_min, kind, emb, entities_json, evergreen_score, first_seen)`.
- **Janela de 120 dias** (configurável por fonte) — separada do `window_h` das notícias. Fontes `longform: true` no `sources.yaml` alimentam o índice; as demais podem entrar por `kind=longform|analysis` (A-3) quando `reading_min ≥ 8` ou "wordcount" disponível.
- **Backfill** das fontes que têm API pública: a piauí é WordPress → testar `https://piaui.folha.uol.com.br/wp-json/wp/v2/posts?per_page=100&page=N&_fields=id,date,link,title,excerpt,author,categories,tags` (mesmo padrão que `factcheck.fetch_lupa` usa para a Lupa; resolver `categories/tags` via `/wp-json/wp/v2/categories`). **[não verificado: acesso e campos; a máquina de revisão não alcançou o domínio]**. Se a API estiver fechada, usar RSS paginado (`?paged=N`) até o limite que o feed oferecer.
- **Do feed, capturar:** `category` (feedparser `e.tags`), `dc:creator` (`e.author`), `content:encoded` (primeiro parágrafo/primeiros 600 chars como `dek` quando o `summary` for curto/ruído), `wp:post-type`. Hoje `collectors.fetch_rss` ignora tudo isso. Estimar `reading_min` por `len(content:encoded)/1000` palavras quando houver corpo no feed (**sem scrape**).
- Exclusões: `kind in {podcast, video, live, service}`, resumo `None`, itens < 4 min de leitura (a menos que `kind=longform` declarado pela fonte), páginas de agenda/newsletter. Regra específica para piauí: tratar "Foro de Teresina" e "Anais da Piauí" conforme `section`/categoria **[verificar categorias reais no feed]**.

### C-2 · Duas relações em vez de uma
| Relação | Pergunta | Janela | Rótulo na UI |
|---|---|---|---|
| **Sobre esta história** | a peça trata do **mesmo fato/desdobramento**? | 0–14 dias | "Análise desta pauta" |
| **Pano de fundo** | a peça explica o **contexto** (instituição, personagem, tema)? | até 120 dias | "Para entender melhor" |
Cada sugestão carrega `relation`, `age_days`, `why` (termos/entidades em comum + 1 frase: "cita Mendonça e o caso Master"), `reading_min`, `authors`, `kind`.

### C-3 · Pontuação (substitui `entity_match` binário no longform)
```
score = 0.45·cos(emb[story], emb[longform])                    # título+dek ↔ centroide da história (títulos+deks)
      + 0.30·Σ idf(entidade ∩) / Σ idf(entidade da peça)      # entidades canônicas ponderadas (A-2)
      + 0.10·recency(age; meia-vida 21 d para "sobre", 90 d para "fundo")
      + 0.10·quality(source.factuality, kind, reading_min)
      − 0.25·redundância (fonte já cobre a história sem ser análise)
      − 0.20·repetição (peça já usada em outra história)
```
- Pré-filtro obrigatório: ≥ 1 entidade **específica** (não genérica) **ou** `cobertura_título ≥ 0,12` — preserva a lição do viés de seleção documentada em `app.py:776-783`.
- Seleção final por **MMR** (relevância − similaridade entre sugestões) com ≤ 1 por fonte e ≤ 3 por história; cada peça aparece na história onde mais pontua (mantém F3.3).
- Pesos são ponto de partida; calibrar por nDCG@3 no conjunto C (seção 8).

### C-4 · Peças **da piauí** em destaque (sem favorecer indevidamente)
- Pesos **neutros** entre fontes de longform (sem bônus para a piauí no score); a presença dela vem do índice persistente (C-1) e da **diversidade de fonte** (MMR). Se o dono quiser curadoria, usar lista editorial explícita e rotular como "seleção do editor".
- Quando a piauí tem peça relevante e a pauta tem ≥ 4 veículos, mostrar até 1 piauí + 1 Pública/Intercept/Repórter Brasil + 1 internacional longform (cota de diversidade de **posição editorial**, não só de fonte).

### C-5 · "Leituras da semana" (produto independente das histórias)
Nova página `docs/leituras.html` + `docs/leituras.xml` (RSS):
- Top ~12 peças de fôlego dos últimos 7–10 dias: `score = relevância às pautas dos últimos 7 dias + qualidade + diversidade de fonte`. Agrupar por pauta (hub) ("Sobre a fuga de Flávio · 3 leituras").
- Seção "do arquivo" (evergreen): 3 peças ≥ 30 dias com `evergreen_score` alto (poucas entidades datadas, sem "hoje/ontem/esta semana", `kind` ensaio/perfil/explicativo).
- Gerada no mesmo `app.py` (sem custo extra).

### C-6 · Fontes de longform a testar (todas **[não verificadas]**)
Brasil: **Serrote** (IMS), **Quatro Cinco Um**, **Núcleo Jornalismo**, **Ponte Jornalismo**, **Sumaúma**, **Outras Palavras**, **Le Monde Diplomatique Brasil**, **Matinal**, **Folha Ilustríssima/Estadão Aliás/Valor Eu&** (seções de longform de veículos já coletados — usar `section` + `kind`), **Revista Questão de Ciência**, **Agência Pública/Intercept/Repórter Brasil** (já há), **Nexo** (já há; separar "Expresso" de ensaios).
Exterior: **The Atlantic**, **The New Yorker**, **NYRB/LRB**, **Foreign Affairs**, **Rest of World**, **Americas Quarterly**, **Mongabay**, **Brazilian Report**.
Para cada uma: endpoint, políticas de uso, `kind_default`, viés inicial **conservador (centro até evidência)** — mesma regra de `PLANO.md` 5.1, registrar em `CURADORIA_VIES.md`.

### C-7 · UI mínima
- Cartão "Aprofunde-se": título, veículo, autor, `reading_min`, data, rótulo `relation`, linha `why`.
- Filtro "só com leitura longa". Link **sempre** para o original; **não** reproduzir o texto (apenas o dek público, como hoje).
- `como-lemos.html`: documentar os critérios, incluindo os limites (matching automático, sem juízo de qualidade).

---

## 7. Eixo D — Otimizações transversais (resumo)

| Tema | Ação | Ref. |
|---|---|---|
| Janela e cap | Remover teto por fonte; cluster esparso/vetorizado | F-01, F-14 |
| Fuso | `timegm`; clamp; migração do cache | F-02 |
| Cache de CI | chave por `run_id` + `restore-keys`; modelo ONNX em cache | F-13, A-5 |
| Publicação | `deploy-pages` ou branch órfã; não commitar `data.json` a cada 30 min | F-13 |
| Arquivo diário | gravar só `stories` enxutas (ids/links/contagens) ou `.json.gz` | F-15 |
| Saúde | alerta quando `last72h < 3` por 3 rodadas; relatar `kept/in_window` | F-11, F-01 |
| Checagens | 0 matches hoje; ver nota abaixo | — |
| Observabilidade | `data.json.meta = {model, versions, thresholds, run_ms, n_candidates}` | A-5 |

**Checagens (fora do foco, mas conectado):** o plano anterior concluiu que o teto léxico foi atingido. Com A-5 (embedding) + A-2 (entidades) a **extração de alegação** (F4.0) fica viável: casar `título da checagem` (que já traz a alegação) contra o **dek** das matérias com cos ≥ τ + número/entidade em comum. `verdict_from_title` é heurístico; manter e testar. Aos Fatos vem com link de redirecionamento do Google News — resolver o destino real (HEAD com `allow_redirects`) ou documentar.

---

## 8. Avaliação e portões (condição para cada fase)

Construir antes de mexer nos matchers; congelar em `tests/fixtures/`.

1. **Corpus congelado:** `tests/fixtures/corpus_2026-10-31.json` (título, dek, fonte, ts, link) a partir do cache do zip — **após corrigir o fuso (F-02)**.
2. **Agrupamento (A):** reaproveitar `tests/eval_pairs.jsonl` e ampliar para ≥ 300 pares, **amostrando do pré-filtro** (lição já documentada) e **incluindo hard negatives de intrusos** da seção 2. Métricas: P, R, F0.5 e **pureza por cluster** nos 20 maiores grupos (revisão manual do implementador, listar em `docs/revisao_clusters.md`).
3. **Longform (C):** novo `tests/longform_pairs.jsonl` com ≥ 120 pares (história×peça) rotulados em **3 níveis** {2=mesmo fato, 1=pano de fundo útil, 0=irrelevante}, com **≥ 40 pares de piauí**. Métricas: P@3, nDCG@3, e **cobertura** (% de histórias com ≥ 1 sugestão relevante; hoje 0,8 %). Piso sugerido: P@3 ≥ 0,85, cobertura ≥ 25 % em dia de pauta quente.
4. **Internacional (B):** ≥ 150 pares, positivos ≥ 40; R ≥ 0,85, P ≥ 0,95.
5. **Dois anotadores.** O plano anterior assume anotador único (o agente). Para tratar P/R como benchmark, rotular uma amostra de 60 pares por uma segunda pessoa (o dono) e reportar concordância (κ). Pares discordantes = "borderline", fora do portão.
6. **Regressão em CI:** `tests/test_eval.py` e `tests/test_connections.py` leem **somente** fixtures (F-12). Adicionar `tests/test_ids.py` (estabilidade), `tests/test_timezones.py`, `tests/test_sanitize.py` (`None`), `tests/test_kind.py`, `tests/test_sources_schema.py` (campos novos).
7. **Relatório por rodada:** `state/quality.json` com P/R no fixture, nº de histórias, mediana de veículos independentes, % com longform/world, tempo de rodada.

---

## 9. Ordem de execução (com critérios de pronto)

### Fase 0 — Correções de dados (1–2 dias) · desbloqueia tudo
- F-02 (fuso) + migração · F-01 (cap) · F-07 (`None`) · F-11 (CNN) · F-13 (cache/publicação) · F-12 (fixtures) · F-09 (tokenização básica) · F-15 menores.
- **DoD:** 75 testes ✔ + novos; `kept == in_window`; nenhum `ts` > `now+5min`; CI salva cache novo a cada rodada.

### Fase 1 — Identidade e coerência (2–3 dias)
- A-6 (ids persistentes + alias) · A-4 passos 4–5 (coerência + mesma fonte 2×) · F-05 (medoide) · A-8 (ranking) · F-04.
- **DoD:** F-03 e F-04 atendidos; os 3 intrusos e os 2 representantes errados da seção 2 corrigidos; UI resolve alias.

### Fase 2 — Camada semântica incremental (3–4 dias)
- A-5 (ONNX/fastembed + `features` no SQLite) · A-1 · A-2 (`entities.yaml`, IDF de entidade) · A-4 pontuação por regressão logística · A-3 (`kind`) · A-7 (grupos independentes + sindicalização).
- **DoD:** R do agrupamento ≥ 0,75 com P ≥ 0,96; rodada no Actions < 3 min incluindo modelo em cache; `counts.independent` exposto e usado na barra.

### Fase 3 — Longform e piauí (3–4 dias)
- C-1 (índice, backfill, captura de metadados) · C-2/C-3 (duas relações, scorer, MMR) · C-5 (leituras da semana) · C-7 (UI) · C-6 (2–4 fontes novas verificadas).
- **DoD:** cobertura ≥ 25 % em dia quente (medida em fixtures + 3 rodadas reais); P@3 ≥ 0,85; zero podcast/vídeo; piauí aparece com `why` legível.

### Fase 4 — Internacional (3 dias)
- B-1 (fontes, `country/bloc`) · B-2 (cluster intl) · B-3 (multilíngue) · B-4 (três vistas).
- **DoD:** R_intl ≥ 0,85 e P ≥ 0,95 em ≥ 150 pares; ≥ 25 % das histórias com 3+ veículos têm "Lá fora"; seção "Só lá fora" funcionando.

### Fase 5 — Produto e acabamentos
- A-9 (enquadramento) · timeline de histórias (A-6) · documentação (`README`, `PLANO*.md`, `como-lemos.html`, `CURADORIA_VIES.md`, `ESTRATEGIA_AGREGACAO.md`) atualizados com os números **novos medidos**.

**Cada fase termina com:** testes verdes, `state/quality.json` anexado ao PR, atualização do `README` (números reais — hoje o README cita "26 testes" e o plano fala em 8 histórias com Aprofunde-se; medido: 74 testes e 1 de 120 histórias).

---

## 10. Riscos e decisões que cabem ao dono

1. **Robots/paywall:** `enrich.py` ignora `robots.txt` por decisão do dono, e a pasta `ref/bypass-paywalls` acompanha o zip. Este plano **não depende de buscar HTML de matéria**; recomendo manter o princípio de `ESTRATEGIA_AGREGACAO.md` (§2) e remover `ref/` de qualquer distribuição.
2. **Direitos autorais/republicação:** deks e títulos são metadados, mas `PLANO.md` 7.3 já lembra a revisão jurídica. Tradução automática de títulos estrangeiros: opcional e rotulada.
3. **Viés fixo por veículo** com fontes de longform e estrangeiras: documentar em `CURADORIA_VIES.md` e usar "centro até evidência" para fontes novas; evitar atribuir viés a peças individuais.
4. **Grupo econômico** (A-7): decidir se UOL/Folha contam como 1 ou 2 grupos (hoje são empresas distintas com vínculo histórico) — registrar a regra em `como-lemos.html`.
5. **Over-merge continua o pior erro** do produto; preferir deixar duas histórias separadas a fundir fatos distintos.
6. **Custo do modelo no CI:** se ONNX/fastembed não couber no runner, manter TF-IDF no CI e gerar embeddings localmente (`ops/`) gravando `features` no `cache.db` que o CI restaura; **degradar com elegância**.

---

## 11. O que **não** foi verificado

- Nenhum acesso de rede aos veículos (o ambiente de revisão não alcançou `piaui.folha.uol.com.br`); logo, **estrutura real do feed e da API WP da piauí, categorias, `content:encoded`, e a existência/forma das fontes candidatas** (seções B-1 e C-6) precisam ser testadas pelo implementador.
- A suposição de que o bug de fuso vem de `time.mktime` é inferida do padrão de ~+2,9 h nas fontes RSS e ausência nas de sitemap; confirmar com o teste de `TZ`.
- O não-atualização do `actions/cache` com chave fixa é comportamento conhecido do Actions, **não observado nos logs** deste repositório.
- Que o item "Vitória da democracia…" da piauí é podcast é **inferência** (resumo `None`, formato do título, outros 2 itens iguais); confirmar pela categoria do feed.
- Tamanho/latência de modelos ONNX no runner do Actions.
- Os números de 8 histórias com "Aprofunde-se" do README/`PLANO_CONEXOES.md` não reproduzem no `data.json` do zip (1 de 120); pode refletir o estado de outra rodada.

---

### Apêndice — mapa de arquivos a tocar

| Arquivo | Mudanças |
|---|---|
| `collectors.py` | `timegm`; capturar `tags`, `author`, `content:encoded`; sanitizar `None`; `GENERIC_SECTIONS`; API WP opcional |
| `store.py` | tabelas `features`, `longform`, `stories`, `story_members`, `story_alias`, `story_events`; remover `PER_SOURCE_CAP`; migração de `ts` |
| `app.py` | quebrar em módulos: `repr.py`, `cluster.py`, `entities.py`, `longform.py`, `world.py`; manter assinaturas públicas usadas pelos testes |
| `sources.yaml` | `group`, `country`, `lang`, `bloc`, `kind_default`, `section_map`, `wire_partners`; fontes novas |
| `entities.yaml` (novo) | registro canônico PT/EN/ES |
| `models/pair_lr.json` (novo) + `ops/train_pair_model.py` | pesos do `pair_score` |
| `ops/` | `build_fixture.py`, `eval_longform.py`, `eval_world.py`, `quality_report.py` |
| `tests/` | fixtures congeladas; testes novos listados em §8 |
| `.github/workflows/collect.yml` | cache por `run_id`, modelo em cache, deploy-pages |
| `docs/index.html` | alias de `?story=`, `independent`, cartões de leitura/Lá fora, página `leituras.html` |
| `README.md`, `PLANO*.md`, `como-lemos.html` | números reais, novas decisões |
