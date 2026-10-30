# Plano — Balanço: próximas etapas e melhorias

> Situação em 30/10/2026: 20 fontes (16 RSS + 4 via Arc XP/sitemap), ~366 artigos → ~22 histórias por rodada, viés fixo por publicação, 200 checagens (G1 Fato ou Fake + Lupa) cruzadas, interface editorial responsiva. Pipeline: `sources.yaml → collectors.py → app.py → docs/data.json → docs/index.html`.

Unidade de esforço: **1 sessão ≈ 1–2 h de trabalho focado**.

## Ordem recomendada (resumo)

| # | Fase | Por que agora | Esforço |
|---|------|---------------|---------|
| 1 | Robustez operacional | Base pronta (cache, 304, retry, health); faltam agendamento e testes | 1 sessão restante |
| 2 | Qualidade do agrupamento | Maior fonte de erro visível hoje | 3 sessões |
| 3 | Enriquecimento sem paywall | Dek/imagem/editoria com risco baixo | 2 sessões |
| 4 | Checagem: corpus + revisão | Factualidade é o diferencial vs. RSS | 3 sessões |
| 5 | Fontes: 2ª leva + governança de viés | Cobertura e credibilidade | 2 sessões |
| 6 | Produto: arquivo, feed próprio, metodologia | Virar "site de verdade" | 3 sessões |
| 7 | Publicação + jurídico | Antes de qualquer lançamento | 2 sessões + terceiros |

**Total estimado: ~18 sessões.** Fases 1–2 são pré-requisito das demais; 3–6 podem rodar em paralelo parcial.

---

## Fase 1 — Robustez operacional (fazer primeiro)

Hoje cada rodada rebaixava tudo, sem cache, sem log e sem aviso quando uma fonte morria.
*Status 30/10: 1.1, 1.2, 1.3 prontos; 1.4 parcial (health.json + selo na UI, sem e-mail/webhook).*

- [x] **1.1 Cache SQLite incremental** — `state/cache.db` com tabelas `articles` (link UNIQUE, first_seen), `http_state` (ETag/Last-Modified por URL), `fetches` (por fonte por rodada) e `runs` (resumo). Só baixa o novo; rodada quente leva ~4 s. Flags: `--fresh` (ignora cache), `--window N` (janela em horas), `--db PATH`.
- [x] **1.2 HTTP condicional** — envia `If-None-Match`/`If-Modified-Since`; respeita 304 (confirmado em G1, Folha, UOL). Reduz carga e risco de bloqueio.
- [x] **1.3 Retry + backoff** — 1 retry com espera em `collectors._http`; timeout por fonte; fonte com erro usa o cache (status `stale`).
- [~] **1.4 Saúde das fontes** — `state/health.json` por rodada + selo "instável" no trilho + aviso no console após 2 erros seguidos. Falta: e-mail/webhook.
- [x] **1.5 Agendamento (Via B)** — `.github/workflows/collect.yml`: roda `app.py` a cada 30 min, `cache.db` via `actions/cache`, commit de `data.json`/`health.json`/ledger. Falta: criar o repo remoto, push e ativar Pages (passos no README).
- [ ] **1.6 Testes mínimos** — `pytest` com fixtures: canonização de URL, parse de sitemap, extração de veredito, matching sintético. Rodar antes de cada mudança no núcleo.

**Aceite:** 3 rodadas seguidas sem erro ✓ (20/20 ok); `data.json` regenerado em ~4 s com cache quente ✓; alertas testados via `store_alerts` ✓. Falta validar "desligar fonte de propósito" numa rodada real.

## Fase 2 — Qualidade do agrupamento

O TF-IDF atual funciona, mas tem falsos positivos conhecidos (boletins econômicos, séries de galeria como "Pinguins", duplicatas do mesmo veículo).

- [ ] **2.1 Conjunto de avaliação** — rotular ~100 pares título×título (mesma história sim/não) a partir dos dados reais. Sem isso, qualquer ajuste de algoritmo é chute.
- [ ] **2.2 Embeddings com fallback** — `sentence-transformers` (ex.: MiniLM multilíngue) para similaridade semântica; TF-IDF continua como fallback offline. Comparar precisão/recall contra o conjunto 2.1.
- [ ] **2.3 Regras anti-ruído** — mesma fonte + mesma editoria exige limiar mais alto; filtrar séries/galerias por padrão repetitivo; exigir 2+ veículos distintos (já feito) e penalizar pares mesma-fonte.
- [ ] **2.4 Título representante** — em vez do mais longo, escolher o mais informativo/neutro (preferir fonte de factualidade alta, evitar clickbait com `?`/`!`/caixa alta).
- [ ] **2.5 Janela temporal por editoria** — breaking news: 12–24 h; análise/opinião: até 7 dias. Hoje é 48 h fixo para tudo.

**Aceite:** precisão ≥ 90% no conjunto 2.1; zero histórias de veículo único; top-5 histórias do dia sem falsos positivos óbvios por 1 semana.

## Fase 3 — Enriquecimento sem paywall

Sitemaps (Globo/Valor/Gazeta) não trazem resumo — histórias dessas fontes ficam sem dek.

- [ ] **3.1 Dek via metadados públicos** — buscar a página e ler **apenas** `<meta name="description">` ou `description` do JSON-LD (standfirst público). Cache de 24 h. Pular `gazetadopovo.com.br/politica/*` (robots) e qualquer URL com muro.
- [ ] **3.2 Imagens** — usar `image:image` dos sitemaps Globo/Valor no destaque e nas histórias (hotlink com fallback).
- [ ] **3.3 Editoria normalizada** — mapear `republica→Política`, `vozes→Opinião`, etc.; exibir como kicker e permitir filtro por editoria.

**Aceite:** ≥ 80% das matérias com resumo; nenhuma requisição a corpo de paywall; filtro por editoria funcionando.

## Fase 4 — Checagem: corpus, transparência e revisão

Hoje: 200 checagens recentes, casamento léxico, ledger acumulativo. Bom começo, corpus raso.

- [ ] **4.1 Paginar a Lupa** — a API aceita `page`; coletar o histórico completo da categoria Verificação (milhares de itens). G1: avaliar paginação do RSS/páginas seguintes.
- [ ] **4.2 Terceira fonte** — Aos Fatos (tem API/seções de checagem). Mesma normalização de veredito.
- [ ] **4.3 "Verificar este tema"** — botão nas histórias sem match abrindo busca pré-preenchida (Lupa + G1 + Google). Transforma ausência de selo em ação.
- [ ] **4.4 Tooltip "por que este selo"** — mostrar os termos da alegação em comum + link da checagem. Transparência do casamento.
- [ ] **4.5 Fila de revisão em CSV** — exportar `state/revisao_checagens.csv` do ledger (fonte, matéria, veredito, links) para validação humana periódica.
- [ ] **4.6 Matching semântico (depois)** — embeddings para "mesma alegação com outras palavras". Só após 2.1/2.2 prontos. Sem LLM por matéria (manter custo zero).

**Aceite:** corpus > 2.000 checagens; toda história política do dia com alegação checável tem selo ou botão de verificação; fila de revisão gerada e revisada 1×/semana.

## Fase 5 — Fontes: segunda leva + governança de viés

- [ ] **5.1 Novas fontes (candidatas)** — Agência Brasil (pública, RSS aberto), Congresso em Foco, DW Brasil, El País Brasil, Aos Fatos, SBT, Record, Band, Veja, IstoÉ, Crusoé. Mesmo protocolo da 1ª leva: testar endpoint, registrar em `ESTRATEGIA_AGREGACAO.md`, viés inicial conservador (centro até evidência).
- [ ] **5.2 Documento de curadoria de viés** — critérios escritos para cada posição (-2…+2), exemplos-âncora por fonte, quem decide e changelog (`state/vies_changelog.md`). Viés fixo exige legitimidade processual.
- [ ] **5.3 Revisão trimestral** — reavaliar 3–5 fontes por ciclo com base no ledger de checagens + amostragem de manchetes.

**Aceite:** ≥ 25 fontes ativas; toda fonte com justificativa de viés de 1 parágrafo; changelog iniciado.

## Fase 6 — Produto

- [ ] **6.1 Arquivo por data/editoria** — `docs/2026-10-30.html` + páginas por editoria; edição atual continua sendo `index.html`.
- [ ] **6.2 Feed próprio** — `docs/feed.xml` do Balanço (histórias agregadas) + JSON público documentado.
- [ ] **6.3 Página "Como lemos"** — metodologia, tabela de fontes com viés/factualidade/propriedade, limitações honestas. (Hoje isso vive solto no trilho.)
- [ ] **6.4 Newsletter Blindspot** — template HTML + geração a partir do `data.json`; envio via provedor transacional. Começar semanal, não diário.
- [ ] **6.5 Busca e filtros 2.0** — filtro por veículo, por editoria, destaque de termo, ordenação por "mais divididas".

**Aceite:** arquivo navegável por 30 dias; feed próprio válido; página de metodologia publicada; 1ª newsletter enviada.

## Fase 7 — Publicação

Parcialmente adiantada pela Via B (Actions + Pages cobrem hospedagem e deploy).

- [x] **7.1 Hospedagem estática + Actions** — workflow ativo; repo em `github.com/hcarta/balanco`, Pages servindo `/docs` em `hcarta.github.io/balanco` (verificado 30/10).
- [ ] **7.2 Domínio + analytics mínimo + SEO** (sitemap próprio, Open Graph).
- [ ] **7.3 Revisão jurídica** — termos de uso, política de correção/errata, avaliação do PL 2338/2023 e de republicação de resumos (se Fase 3 publicar deks de terceiros, considerar licenciamento).
- [ ] **7.4 Modelo** — definir antes de escalar: gratuito aberto (como hoje) vs. assinatura estilo Ground.news. Recomendação: manter aberto até ter tração; monetização depois.

**Aceite:** site no ar com deploy automático; jurídico revisado; decisão de modelo registrada.

---

## Riscos transversais

| Risco | Mitigação |
|---|---|
| Endpoint de fonte muda | Fase 1.4 (alerta) + fallbacks documentados |
| WAF/rate limit | HTTP condicional, 1 req/ciclo, UA ASCII, cache |
| Viés fixo contestado | Fase 5.2/5.3 (critérios + changelog + revisão) |
| Selo de checagem errado | Casamento conservador + tooltip 4.4 + fila 4.5; nunca rotular matéria como falsa |
| Escopo explodir | Fases 1–2 primeiro; só então 3–7 em paralelo parcial |

## Sugestão para a próxima sessão

**Fase 1.1 + 1.2 (cache SQLite + HTTP condicional)** — é o que mais reduz custo operacional e risco de bloqueio, e destrava agendamento e arquivo histórico. Dá para entregar em 1 sessão.
