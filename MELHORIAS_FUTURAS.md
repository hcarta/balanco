# MELHORIAS_FUTURAS.md — backlog pós-plano

> Registrado em 02/11/2026, a pedido do dono. Não implementar antes de fechar a
> Fase 5. Cada item tem objetivo, abordagem proposta, aceite e riscos.

---

## 1. Hierarquia a partir das primeiras páginas (Estadão, Folha, O Globo) — ✅ feito (02/11/2026)

> `fetch_front_page` lê as capas dos 3 jornais (12 manchetes, UTF-8) e
> `attach_front_pages` casa por tokens + entidade (≥3 tokens, cobertura ≥0,55,
> âncora de entidade) e calcula `front`, `front_score` e `destaque`
> (0,75 capa + 0,15 cobertura + 0,10 recência; a capa satura em 5 jornais
distintos — regra 2 de 02/11). A chamada de cada pauta é a manchete de capa mais recente,
com subtítulo quando a capa expõe.
> “Em foco” e as 3 laterais passam a usar o destaque; o destaque mostra
> “Abre em N de 3 jornais” com as manchetes (details).
> **Limite:** só casa o que está no feed. Capas com pautas fora do feed (ex.:
> “reforma eleitoral”, “Linha 6”) não casam — para refletir 100% seria preciso
> coletar os artigos da própria capa.

**Atualização (02/11/2026):** 6 jornais (O Globo, Estadão, Folha, G1, UOL, CNN),
lexicon de 13 conceitos e `front_only`; a P1 ligou cada pauta às histórias do
feed (`front_pautas`/`story_ids`/`pauta`) e a P2 expôs “Veja também nesta
pauta (N)” + filtro do feed. Ver `PLAN_PAUTAS_CAPA.md`.

**Objetivo:** o bloco “Em foco” e as 3 histórias de destaque deixam de ser só
“maior nº de coberturas” e passam a refletir o que os três jornais de referência
**abrem na primeira página**, cruzando semelhanças entre eles.

**Estado atual:** `renderFeatured()` escolhe a história com `counts.total` máximo
(`docs/index.html:603-606`) e as 3 laterais por `centerTrusted` (nº de veículos de
centro com factualidade alta). Não há sinal de “primeira página”.

**Abordagem proposta:**
1. **Coletor de capa** (`collectors.py`): para cada um dos 3 veículos, buscar a
   home pública e extrair a lista ordenada de manchetes (posição = peso). RSS de
   capa, quando existir, é preferível (mais estável). Cache de 30 min, 1 req/veículo.
2. **Casamento capa → história**: usar o matcher existente (título + âncora de
   entidade/número) contra as histórias do dia. Cada capa gera
   `front_page: {source, position, headline}`.
3. **Score de destaque** (novo, em `app.py`):
   ```
   front_score = Σ (peso_posição × 1[o veículo abre com a história])
   destaque = 0.5·norm(front_score) + 0.3·norm(counts.total) + 0.2·recência(18h)
   ```
   `peso_posição`: topo da página 1,0; meio 0,7; fim 0,4.
4. **UI:** o “Em foco” passa a mostrar “**Abre em 2 de 3 jornais**” e, ao expandir,
   as três manchetes de capa (transparência). As 3 laterais usam o mesmo score.

**Sugestões adicionais de engajamento (pedido do dono):**
- **“X de 3 jornais abrem com isso”** — sinal de consenso editorial forte.
- **“Por que está em foco”** — uma linha gerada de regras (“2 dos 3 jornais de
  referência abrem com o tema; 12 veículos cobrem”).
- **Diversidade no topo** — não repetir o mesmo tema/hub nas 3 laterais.
- **“Continuar de onde parou”** — usar o `localStorage` já existente (`?uso=1`)
  para marcar histórias já abertas e não repeti-las no topo.
- **A/B test** — alternar capa×cobertura por semana e medir cliques no analytics
  local (já implementado, sem rede).
- **Frescor** — dar peso extra a histórias com cobertura nas últimas 6 h (liga
  com o item 2).

**Aceite:** com as 3 capas coletadas, o destaque é o de maior `destaque`; nenhuma
história sem capa fica à frente de uma com 2+ capas, salvo se tiver 3× mais
cobertura; `/em-foco` mostra a origem (quais jornais).

**Riscos:** capa muda ao longo do dia (cache curto); paywall não afeta a capa;
layout de cada home muda (usar seletores tolerantes + fallback para RSS).

---

## 1a. Legenda de viés e porcentagem nas 3 histórias de destaque — ✅ feito (02/11/2026)

> `biasLegend(s, 'mini')` reutilizada do destaque principal; os 3 cartões agora
> mostram as faixas e % (ex.: “CE 33% · Centro 67%”), com estilo compacto.

**Objetivo:** cada um dos 3 cartões laterais mostra a barra de 5 faixas + as
porcentagens, como no destaque principal.

**Estado atual:** os cartões laterais já têm a `rail-mini` (barra fina), mas **não
têm a legenda com percentuais**; mostram “N veículos de centro · cobertura”.

**Abordagem:** reutilizar `biasBar(s)` (ou uma variante compacta) dentro do
`.hitem`; manter o texto de veículos. No mobile, a legenda quebra em 2 linhas.

**Aceite:** os 3 cartões exibem `Esq./CE/Centro/CD/Dir.` com % (só faixas > 0).

---

## 2. Ordenação em “Todas as histórias”: cronologia × destaque (6 h) — ✅ feito (02/11/2026)

> Backend expõe `recent = {n_6h, n_24h}` (grupos independentes na janela);
> UI tem o controle “Cronologia | Destaque”, persistido em `localStorage` e com
> `aria-pressed`. O modo Destaque ordena por `n_6h`, depois cobertura e recência.

**Objetivo:** o leitor escolhe entre ordem cronológica (padrão atual) e
“destaque”, definido por **repercussão nas últimas 6 h**.

**Estado atual:** `baseOrder()` ordena por hora de `updated` e, dentro da hora,
por `counts.total` (`docs/index.html:539-547`). Não há controle de ordenação.

**Abordagem:**
1. Backend: expor em cada história `recent = {n_6h, n_24h}` — contagem de
   coberturas com `first_seen`/`published` dentro da janela (já temos os campos).
2. UI: um segmented control “Cronologia | Destaque” ao lado de “Todas as
   histórias”; persistir a escolha em `localStorage`.
3. `destaque` ordena por `n_6h`, desempata por `counts.total` e recência.

**Aceite:** alternar o controle reordena sem recarregar; a escolha persiste.

**Riscos:** `n_6h` pode premiar um único veículo que republicou; usar
`counts.groups` (grupos independentes) na janela, não matérias.

---

## 3. Seção de colunas e opinião (esquerda/centro/direita), 3× ao dia — ✅ feito (02/11/2026)

**Objetivo:** complementar as notícias do dia com **uma coluna/opinião de cada
lado**, atualizada pelo menos 3 vezes ao dia.

**Estado atual:** `piece_kind` já classifica `opinion` (URL/editoria/título) e
essas peças **não contam como cobertura** (ficam como “enquadramento”). Não há
seção dedicada.

**Abordagem:**
1. Backend: montar `opiniao = {L:[], C:[], R:[]}` no payload, pegando
   `piece_kind == "opinion"` das últimas 24 h, 1 por bucket/veículo, com dedup.
   Preferir colunistas de fontes com `factuality` alta.
2. Atualização 3×/dia: o CI já roda a cada 30 min; fixar janelas (manhã, tarde,
   noite) para trocar a seleção, evitando “piscar” a cada rodada.
3. UI: seção/card “Opinião de hoje” com 3 cartões (Esq./Centro/Dir.), chip de
   viés, veículo e link; rótulo explícito “opinião, não cobertura”.
   Página própria `docs/opiniao.html` se o volume justificar.

**Aceite:** 3 cartões (quando houver peça de cada lado), sem repetir veículo,
atualizados em 3 janelas; nada disso entra na barra de viés nem no blindspot.

> **Implementado:** `build_opiniao` seleciona 1 peça por lado (L/CL, C, CR/R),
> dedup por veículo, priorizando factualidade; janelas 00h/12h/18h com seleção
> persistida em `state/opiniao.json`; seção “Opinião de hoje” no site, rotulada
> “opinião, não cobertura”. Fora da barra e do blindspot.

**Riscos:** opinião enviesada por definição — deixar claro na UI; não usar para
“consenso”; evitar clickbait com o mesmo filtro de título.

---

## 4. Mobile: eliminar o estouro horizontal — ✅ feito (02/11/2026)

> Corrigido junto da Fase 5. Causa: o `section-head` (título + 2 selects de
> 170px + contador) tinha largura mínima de ~590px e arrastava a coluna do grid.
> Correção: `.main` com `minmax(0,1fr)` também no mobile e um bloco ≤760px com
> `min-width:0` em `#feedCol/#feed/.story/.compare/.pauta/.beyond`, `edwrap`
> quebrando linha e selects flexíveis. Medido em iframe: **overflow 0 em
> 320/375/430 px** (antes 613 px de largura).

**Objetivo:** o site não ultrapassa a largura da tela em 320–430 px.

**Diagnóstico provável (a confirmar em 375 px):**
- **Nav** (`.nav .wrap`): marca com `white-space:nowrap` + busca de **190 px**
  fixa (`flex:0 0 auto`) + botão de tema. Em 375 px, o mínimo passa da largura;
  `.links` rola, mas os itens fixos empurram a página.
- **Barra de viés**: 240 px fixos (cabe em 375, mas pode somar com a legenda).
- **Comparar os lados**: em 721–1000 px rola dentro; abaixo de 720 empilha —
  conferir se o `overflow-x:auto` do grid não vaza.
- **Timeline** (`.tlrow`) e imagens do hero podem ter largura fixa.

**Abordagem:**
1. Auditar em 320/375/430 px com `document.documentElement.scrollWidth` e listar
   os elementos com `right > innerWidth`.
2. Nav: em ≤720 px, busca com `width:100%` em linha própria (ou 120 px) e
   `min-width:0` nos filhos; `overflow:hidden` no `.wrap` como cinto.
3. `body{overflow-x:hidden}` só como último recurso (esconde o sintoma; preferir
   corrigir o elemento).
4. Testar Comparar (5 colunas), timeline, barra e cards.

**Aceite:** `scrollWidth === innerWidth` em 320, 375 e 430 px; nenhum conteúdo
cortado; navegação por toque funciona.

---

## 5. Backlog editorial: notícias da semana como base de métricas — ✅ feito (02/11/2026)

**Objetivo:** manter um recorte estruturado das notícias da semana para (a) criar
métricas de comparação entre edições, (b) gerar resumos automáticos e (c) ligar
essas notícias às leituras longas com mais precisão.

**Abordagem:**
1. Persistir um `week_digest` (últimos 7 dias) com: id da história, título,
   contagens por faixa e grupos, entidades, números do evento e links.
2. Métricas de comparação: nº de histórias, mediana de grupos independentes,
   % de blindspots, % com leitura longa, cobertura por faixa — por dia/semana.
   Guardar em `state/metrics/AAAA-WW.json` e mostrar uma série simples no site.
3. Resumos: gerar 1–2 frases por história da semana (regras/lead; LLM só opt-in)
   para reuso em “Leituras”, newsletter e arquivo.
4. Ligação com longas: usar entidades + números do digest para pontuar leituras
   (substitui/expande o scorer atual do Aprofunde-se e a cota da piauí).
5. Aceite: `week_digest` reprodutível de um snapshot; métricas comparáveis entre
   duas semanas; toda leitura longa aponta para uma história do digest.

**Riscos:** custo de armazenamento (usar slim + gzip); resumo automático pode
errar — rotular como automático e manter link.

> **Implementado:** `digest.py` grava `state/metrics/AAAA-Www.json` (por dia),
> `state/week_digest.json.gz` (slim, 7 dias, resumo automático) e
> `state/pautas_metrics.json`; o site mostra “A semana em números” (histórias,
> grupos medianos, blindspots) e o acompanhamento de capas (sem pauta,
> emergentes). `python report.py` imprime a série.

## Ordem sugerida

1. **4 (mobile)** — barreira de leitura, mais urgente.
2. **1a (legenda no destaque)** — pequeno e visível.
3. **2 (ordenação)** — pequeno, melhora navegação.
4. **1 (capas)** — maior esforço (coletor + score + UI).
5. **3 (opinião)** — produto novo; depende de curadoria de colunistas.
