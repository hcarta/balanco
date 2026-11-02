# PLAN_FINAL.md — Plano para a versão final do Balanço

> Para um **modelo menor** implementar, passo a passo. Leia antes:
> `PACOTE_REVISAO.md` (estado medido), `PLAN_FALSAS_EQUIVALENCIAS.md` (gate F0–F5),
> `PLAN_F2_DIAGNOSTICO.md` (por que o treino F2 falhou), `PLAN_CLAUDE.md` (diagnóstico).
> Entradas novas desta rodada: `plan_opus.txt` (revisão parcial do Claude Opus),
> `comparacao_fontes_claude.csv` e `comparacao_fontes_gemini.csv` (2 modelos avaliando viés/factualidade).

---

## 0. Estado medido (01/11/2026)

- **53 fontes** (36 BR + 17 intl); ~440 histórias/rodada; CI a cada 30 min (deploy-pages).
- **Testes: 141 passed + 56 xfailed** (`python -m pytest tests/ -q`).
- Viés fixo por fonte (`sources.yaml`, escala −2..+2); LLM opt-in (`--llm`).
- 3 colunas hoje (Esq/Centro/Dir); alvo desta rodada: **5 colunas**.
- C-3 híbrido no Aprofunde-se (17 histórias/rodada); `--embed` ONNX no CI.

## 1. Validação do `plan_opus.txt` (o que vale e o que não vale)

O `plan_opus.txt` mistura achados reais com **equívocos do subagente**. Antes de
agir, desconsidere o que já está resolvido ou é impreciso:

| Afirmação do plan_opus | Veredito |
|---|---|
| "No dark mode" | **Falso** — há tema escuro (`docs/index.html` linhas ~44–49, `themeBtn`) |
| "No CSS variables" | **Falso** — usa `--L/--C/--R/--ink/--hair…` em `:root` |
| "`render_html()` gera HTML por f-string" | **Falso** — `app.py` só escreve `data.json`/`feed.xml`; a UI é o `docs/index.html` estático que lê `data.json` |
| "funções `build_tfidf_matrix/cluster_stories/_anchor_ok`" | **Nomes errados** — reais: `tfidf_matrix()`, `cluster()`, `_pair_decision()` |
| `dt_hours` = 0 no treino F2 | **Verdadeiro** (já em `PLAN_F2_DIAGNOSTICO.md` §5.1) — bloqueia conclusão sobre sinal temporal |
| F3 gate duro vs veto, ambos não implementados | **Verdadeiro** |
| `app.py` monolítico (~1700 linhas) | **Verdadeiro** |
| Serial HTTP (53 fontes), enriquecimento serial | **Verdadeiro** |
| Limiares hardcoded espalhados | **Verdadeiro** |
| Aos Fatos via Google News devolve redirect | **Verdadeiro, não resolvido** |

---

## 2. Revisão de viés e factualidade (Claude × Gemini)

### Métricas medidas (53 fontes)

- Correlação de viés **Claude×Gemini = 0,95** (concordância alta; eles se validam).
- Correlação **atual×Claude = 0,83** e **atual×Gemini = 0,83** — o gap está nas
  fontes novas (longform e LatAm), onde o atual ficou em `0.0` ("centro até evidência").
- Concordância de factualidade (3 níveis): **0,85** em todos os pares.

### Regra de reconciliação (proposta)

1. `consenso = round(media(claude, gemini), 1)`.
2. Se `|claude − gemini| ≤ 0.5` → **aplica consenso automaticamente**.
3. Se `|claude − gemini| > 0.5` ou `|consenso − atual| ≥ 1.0` → **marcar `REVISAR`**
   para decisão do dono (nunca aplicar automático em swing grande).

### Aplicação automática (ambos os modelos concordam em mover, mesmo sentido)

| Fonte | atual | claude | gemini | → aplicar |
|---|---|---|---|---|
| Brasil 247 | −1.4 | −1.8 | −2.0 | **−1.8** |
| R7 | +0.5 | +1.0 | +1.0 | **+1.0** |
| Quatro Cinco Um | 0.0 | −0.7 | −0.5 | **−0.6** |
| Núcleo Jornalismo | 0.0 | −0.5 | −0.5 | **−0.5** |
| Outras Palavras | 0.0 | −1.5 | −1.5 | **−1.5** |
| Le Monde Diplomatique BR | 0.0 | −1.5 | −1.5 | **−1.5** |
| Ponte Jornalismo | 0.0 | −1.0 | −1.5 | **−1.2** |
| Sumaúma | 0.0 | −1.0 | −1.5 | **−1.2** |
| La Nación | 0.0 | +0.8 | +0.5 | **+0.6** |
| Infobae | 0.0 | +0.8 | +0.5 | **+0.6** |
| Clarín | 0.0 | +0.7 | +0.5 | **+0.6** |
| MercoPress | 0.0 | +0.5 | +0.5 | **+0.5** |

### `REVISAR` (discordância ou swing grande — decisão humana)

| Fonte | atual | claude | gemini | problema |
|---|---|---|---|---|
| Estadão | −0.1 | +0.5 | +1.0 | swing grande; ambos querem mover à direita |
| IstoÉ | 0.0 | +1.0 | 0.0 | Claude vê direita, Gemini centro |
| Veja | +0.5 | +1.1 | +0.5 | Claude mais à direita |
| InfoMoney | +0.2 | +0.4 | +1.0 | Gemini mais à direita |
| Crusoé | +1.0 | +1.5 | +1.0 | |
| Agência Pública | −0.8 | −1.0 | −1.5 | |
| Nexo Jornal | −0.4 | −0.5 | −1.0 | |
| Folha de S.Paulo | −0.3 | 0.0 | −0.5 | Gemini à esquerda, Claude centro |

### Factualidade (ambos concordam em mudar vs atual)

| Fonte | atual | → ambos | ação |
|---|---|---|---|
| Infobae | high | mixed | **downgrade** |
| Outras Palavras | high | mixed | **downgrade** |
| Revista Oeste | low | mixed | **upgrade** (ambos) |
| Terra | mixed | high | **upgrade** |

Dissonância a arbitrar: **Diário do Centro do Mundo** (atual `low`, Claude `mixed`,
Gemini `Baixa`) e **Jovem Pan** (atual `mixed`, Gemini `Baixa`).

---

## 3. Nova classificação em 5 colunas (aproximando Ground.news)

### Mapeamento (única constante configurável)

```python
# app.py — substitui bucket() atual
def bucket(score: float) -> str:
    if score <= -0.8: return "L"     # esquerda
    if score <= -0.3: return "CL"    # centro-esquerda
    if score <   0.3: return "C"     # centro
    if score <   0.8: return "CR"    # centro-direita
    return "R"                       # direita
```

> Limiares −0.8/−0.3/+0.3/+0.8. Se quiser centro mais estreito, é mudar uma
> constante `BIAS_EDGES = (-0.8, -0.3, 0.3, 0.8)` e os testes acompanham.

### Pontos de mudança (completo, para não quebrar nada)

**`app.py`**
- `bucket()` → 5 valores.
- `blindspot_of()` → agrega bloco esquerdo = `L+CL`, direito = `CR+R`, centro = `C`.
  Regra atual preservada: só-marco 3+ coberturas; só-centro → `None`; um bloco com
  ≤15% → blindspot daquele lado. Novo retorno continua `left|right|None`.
- `independent_counts()` e `counts` → 5 chaves `{L, CL, C, CR, R}` (soma de grupos).
- `pct` → 5 percentuais.
- `framing_terms()` → 5 buckets.
- `_recompute()` (consolidate) → mesmo tratamento 5 vias.

**`docs/index.html`**
- `const BUCKET = {L:'Esquerda', CL:'Centro-esquerda', C:'Centro', CR:'Centro-direita', R:'Direita'}`.
- `const cls = b => 'b'+b` (classes `bL/bCL/bC/bCR/bR`).
- CSS: novos `--CL`/`--CR` (e `-bg`) em tema claro e escuro. Sugestão: `--CL:#4f7a3b`
  e `--CR:#b08a2e` (tons intermediários entre verde e âmbar atuais).
- Barra de viés: 5 segmentos `<span class="bL|bCL|bC|bCR|bR">`.
- Painel "Comparar os lados": 5 colunas (`col L|CL|C|CR|R`), com `grid-template-columns`
  adaptado (mobile: empilhar).
- `rail-mini` e legenda de viés: 5 faixas.
- `pct` na barra e nos cards.

**`feed.xml` / `data.json`**: schema aditivo — `pct` e `counts` ganham chaves novas;
UI antiga tolera ausência (guardas).

**Testes** (`tests/test_matching.py`, `tests/test_connections.py`):
- `test_bucket_five_columns` (fronteiras −0.8/−0.3/0.3/0.8).
- `test_blindspot_aggregates_leaning_blocks` (L+CL vs CR+R).
- `test_counts_and_pct_five_ways`.
- Atualizar qualquer teste que assere `bucket` 3 vias.

### Blindspot de 5 colunas (especificação)

```
esq = L + CL ; dir = CR + R ; cen = C
tot = esq + cen + dir
tot < 3                 -> None
esq/tot <= 0.15 e dir/tot <= 0.15 -> None   # só centro
esq/tot <= 0.15         -> "left"            # pouca esquerda
dir/tot <= 0.15         -> "right"           # pouca direita
senão                   -> None
```

---

## 4. Fases de implementação (ordem recomendada)

Cada fase termina com testes verdes e commit próprio. Não avance sem o aceite.

### Fase 0 — Correções e higiene (1 dia) — ✅ parcial (01/11/2026)

- [x] **`dt_hours` corrigido**: `ops/rebuild_pair_dt.py` recomputa o Δt pelo cache
      (143/154 pares; mediana 8,7 h). Re-treino: **AUC 0,835 → 0,904**; em P≈0,94 o
      recall sobe 0,43 → 0,53. Ainda sem P≥0,97 & R≥0,80.
- [x] **Aos Fatos**: o redirect do Google News não resolve (HTTP 302 para si mesmo).
      `fetch_aosfatos` mantém os títulos/vereditos do Google e troca o link pela URL
      real achada no `sitemap-noticias.xml` (match ≥80% de tokens + 3 em comum);
      senão, busca do próprio site. 8/20 links diretos na amostra; teste de
      conservadorismo em `test_aosf_link_matcher_is_conservative`.
- [ ] **Limiares hardcoded** → `Config`: **adiado** (refactor amplo, risco>ganho
      imediato; fazer junto da Fase 4).
- [x] `python -m pytest tests/ -q` → **142 passed + 56 xfailed**.

### Fase 1 — Viés e factualidade (½ dia + revisão do dono) — ✅ parcial (01/11/2026)

- [x] `ops/reconcile_fontes.py` gera `state/consenso_fontes.csv` (atual, claude,
      gemini, consenso, ação, factualidade).
- [x] **22 fontes** de viés aplicadas (consenso de 2 modelos; regra: discordância
      ≥ 0,5 vai para o dono). Destaques: longform novo (−0,5 a −1,5), LatAm (+0,5 a
      +0,7), R7 +1,0, DCM −1,9.
- [x] **4 factualidades** aplicadas (Infobae e Outras Palavras → mixed; Oeste e
      Terra → upgrade). `sources.yaml` + `CURADORIA_VIES.md` + changelog sincronizados.
- [ ] **10 fontes em `REVISAR`** (decisão do dono): Estadão, IstoÉ, Veja, InfoMoney,
      Crusoé, Agência Pública, Nexo, Folha, Ponte, Sumaúma.
- [x] Aceite: **142 passed + 56 xfailed**; distribuição 5 colunas L11/CL9/C19/CR8/R6.

### Fase 2 — 5 colunas (1–2 dias) — ✅ feito (01/11/2026)

- [x] Implementado da §3: `bucket()` 5 vias + `BIAS_EDGES`; `blindspot_of5`;
      `counts`/`pct`/`gc`/`framing` 5 vias; UI com 5 colunas, barra de 5 segmentos,
      cores `--CL/--CR` (claro e escuro), legenda só com faixas presentes, filtros
      Esq/Dir por bloco; `como-lemos.html` explica as 5 faixas.
- [x] Telas médias: rolagem horizontal (colunas de 168px) em vez de esmagar;
      mobile empilha.
- [ ] Validar visualmente no `http://localhost:8003` (5 colunas, barra, blindspot,
      framing) e no mobile.
- [ ] Medir distribuição: % de histórias com cada blindspot; garantir que 5 colunas
      **aumenta** histórias "não-blindspot" (mais nuance, menos falso desequilíbrio).
- [ ] Aceite: nenhuma história quebra; `data.json` tem `pct`/`counts` 5 vias; testes verdes.

### Fase 3 — Gate de falsas equivalências (1–2 dias, após Fase 0) — ⚠️ parcial

**Resultado medido (01/11/2026):**
- Modelo re-treinado sem embeddings (uso no cluster): **AUC 0,904**; `state/pair_model.json`
  (18 features, veto 0,25).
- Veto de elo fraco (flag `--pair-model`, off por padrão): veta 6% dos `same`,
  56% dos `related` e 63% dos `different`; +53 grupos numa rodada (1,4%).
- **Regra de conflito de dek** (`_summary_conflict`): quando os dois títulos
  compartilham só macro-tema e os deks não se tocam (<0,05), veta. Testes:
  caso safra Trump × Papa barrado **se o dek existe**; pares legítimos com
  número/multi-palavra preservados; 0 `same` perdidos no conjunto rotulado.
- **Limite descoberto:** o caso reportado continua agrupado porque o grupo é um
  **cluster de tópico (midterms)**, unido por explicadores, e 4 das 5 fontes
  (Valor, O Globo, Band, Gazeta) têm **0% de dek** no cache (sitemap sem
  descrição, embora o meta esteja disponível na página). Título+dek não separam
  tópico de evento.

**Cluster de tópico resolvido (02/11/2026) — A-4 estrutural:**
`STRONG_LINK=0,45` no cluster. Pares fortes fundem direto; elos fracos
(0,38–0,45) só são barrados quando **os dois lados já estão ancorados** em
clusters fortes distintos e sem vizinho forte em comum. Resultado: o caso
safra Trump × Papa separou (15→8 artigos, sem o papa), grupos 3.706→3.807
offline (+2,7%) e 444→462 em produção (+4%), maior grupo 34. Testes travam os
dois lados: ponte fraca não une clusters ancorados; história de 2 fontes
continua fundindo. **144 testes.**

**Fase 3.5 executada (02/11/2026):** enriquecimento em paralelo por host
(6 workers), prioridade para fontes de sitemap sem dek e cap 120/rodada; quando
o meta falta, usa o **lead do corpo público**. Rodada: 1.927 resumos preenchidos,
1.751 corpos, 278 com muro; 307 s no total (limite 10 min). A ponte
Folha×Estadão passou a ser vetada, mas o grupo **continua unido pelos
explicadores** (deks genéricos de midterms, 8–23% de sobreposição) e por pares
com dek curto. Ou seja: **título+dek separam fato de fato; não separam fato de
tópico.** Para isso, a próxima alavanca é A-1/A-2 (features de evento).
Veto segue **desligado** no CI.

- [x] Re-treinar `ops/eval_pair_model.py` com `dt_hours` corrigido (sem embed p/ cluster).
- [ ] Decidir **gate duro × veto** com os números novos; implementar `--pair-model`
      (flag/env `PAIR_MODEL`) com fallback byte-idêntico, e aplicar na coerência.
- [ ] A/B de 3 rodadas (regra × modelo × modelo-sem-embeddings); relatório
      `ops/ab_pair_model.md`. Caso-âncora: safra Trump × Papa deve separar.
- [ ] Aceite: nenhuma história > 60 coberturas sem revisão; zero mistura nos 20 maiores.

### Fase 4 — Arquitetura e qualidade (2–3 dias)

- [ ] Fatiar `app.py`: `cluster.py`, `connections.py`, `hubs.py`, `framing.py`
      (mover, sem mudar comportamento; testes continuam verdes a cada passo).
- [ ] `sources.yaml` com validação de schema (pydantic/jsonschema) no carregamento.
- [ ] Busca HTTP paralela das 53 fontes (ThreadPoolExecutor, teto de concorrência),
      mantendo cache/conditional.
- [ ] Estado global (`_ENT_CACHE` etc.) → passar como contexto onde couber.
- [ ] Aceite: mesma saída byte-a-byte no `data.json` antes/depois do refactor
      (snapshot num run sem rede).

### Fase 5 — UI/UX e acessibilidade (1–2 dias)

- [ ] Painel "Comparar os lados" responsivo com 5 colunas (já na Fase 2); ajustar.
- [ ] ARIA em controles interativos, focus visível, `aria-label` nas barras.
- [ ] Lazy-load de imagens (`loading="lazy"`).
- [ ] Indicador de atualização quando `data.json` muda.
- [ ] Aceite: Lighthouse acessibilidade ≥ 90.

### Fase 6 — Produto final (conforme decisão do dono)

- [ ] Newsletter (escolher provedor) · domínio próprio · SEO (sitemap, meta).
- [ ] Revisão legal (termos, errata, PL 2338/2023).
- [ ] `state/quality.json` anexado ao PR final, com P/R no fixture.

---

## 5. Comandos úteis

```bash
python -m pytest tests/ -q
python ops/eval_pair_model.py --pairs tests/cluster_pairs.jsonl --seed 7
python ops/eval_longform.py --embed
FASTEMBED_CACHE_PATH=state/models python app.py --body --body-cap 40 --embed
python -m http.server -d docs 8003
```

## 6. Riscos

- **5 colunas**: mudar `bucket()` sem migrar `pct/counts/blindspot` juntos quebra a
  barra silenciosamente — migrar tudo na mesma Fase, com testes.
- **Viés**: nunca aplicar `REVISAR` automaticamente; swings grandes são decisão do dono.
- **F3**: gate duro fragmenta; veto é mais seguro para o caso de uso — confirmar com os
  números da Fase 0 antes de travar.
- **Refactor Fase 4**: só mover código; o aceite é saída idêntica (snapshot).
