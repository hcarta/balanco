# Estratégia de agregação — Estadão, O Globo, Valor e Gazeta do Povo

> Verificado em **30/10/2026**. O objetivo é ampliar a cobertura sem violar robots, paywall ou direitos autorais: **manchete + link + data**, nunca o corpo da matéria.

## 1. Diagnóstico (testado, não suposto)

| Fonte | RSS público | Caminho que funciona hoje | Formato | Volume | Observações de robots |
|---|---|---|---|---|---|
| **Estadão** | ❌ (`/feed/` bloqueado) | `estadao.com.br/arc/outboundfeeds/rss/?outputType=xml` | RSS 2.0 (Arc XP) | 100 itens | `robots` declara o sitemap Arc; bloqueia GPTBot/CCBot/ChatGPT-User |
| **O Globo** | ❌ (`/rss.xml` proibido) | `oglobo.globo.com/sitemap/oglobo/news.xml` | Google News sitemap | 720 URLs (~48 h) | `robots` proíbe `/rss.xml` e `/*.json`, mas **não** `/sitemap/` |
| **Valor** | ❌ (404) | `valor.globo.com/sitemap/valor/news.xml` | Google News sitemap | 720 URLs | `robots` **declara** esse sitemap; bloqueia vários bots de IA |
| **Gazeta do Povo** | ❌ (404) | `gazetadopovo.com.br/sitemap.xml` → `YYYY-MM-DD-gnews.xml` | Índice + Google News sitemap | ~100/dia | `robots` declara o sitemap; **proíbe `/politica/`** |

Conclusões:
- Os quatro expõem **endpoint machine-readable sancionado** — não é preciso scraping de HTML.
- Sitemaps de notícias trazem só `title`, `loc` e `publication_date` (sem resumo). Isso basta para agrupar; o resumo é enriquecimento opcional.
- Nenhum deles permite republicar o texto. A estratégia é **agregar e linkar**.

## 2. Princípios

1. **Fonte sancionada primeiro**: RSS/sitemap publicado pelo veículo antes de qualquer HTML.
2. **Só metadados**: manchete, link canônico, data, editoria (derivada da URL) e imagem quando o sitemap oferece.
3. **Zero paywall bypass**: sem login, sem contorno de muro, sem cache de corpo.
4. **Atribuição e link de saída** sempre para o original.
5. **Robots + rate limit**: 1 requisição por fonte por ciclo, `ETag`/`Last-Modified`, intervalo de 15–30 min.
6. **UA honesto e ASCII**: identificamos o agregador. *(Descoberta prática: header com acento/não-ASCII faz o WAF de Poder360/Carta/Oeste devolver 403.)*
7. **Viés fixo por fonte (sem IA por padrão).** Se `--llm` for ativado, não alimentar o modelo com corpo de Estadão/Valor/Gazeta, cujos robots bloqueiam bots de IA — usar **apenas a manchete**.

## 3. Arquitetura

```
sources.yaml ──► collectors.collect_one(source)
                    ├── fetcher: rss      → feedparser
                    └── fetcher: sitemap  → urlset | sitemapindex (resolve índice por data)
                          ↓
                 normalização (title, link, published, ts, section)
                          ↓
                 dedup por link + janela de 48 h
                          ↓
                 cluster (TF-IDF) → viés → data.json → UI
```

Arquivos:
- `collectors.py` — adaptadores `fetch_rss` / `fetch_sitemap` + dispatch.
- `sources.yaml` — cada fonte declara `fetcher: rss|sitemap` e a URL em `rss`.
- `app.py` — pipeline inalterado; passou a consumir `collect_one`.

## 4. Endpoints adotados

```yaml
estadao: https://www.estadao.com.br/arc/outboundfeeds/rss/?outputType=xml   # rss
oglobo:  https://oglobo.globo.com/sitemap/oglobo/news.xml                  # sitemap
valor:   https://valor.globo.com/sitemap/valor/news.xml                    # sitemap
gazeta:  https://www.gazetadopovo.com.br/sitemap.xml                       # sitemap (índice)
```

## 5. Fallbacks (se um endpoint mudar)

Ordem de tentativa por fonte:
1. Endpoint first-party acima.
2. Outro feed do mesmo grupo (ex.: Valor também publica em `valor.globo.com/sitemap/valor/AAAA/MM/DD_1.xml`).
3. **Google News RSS**: `https://news.google.com/rss/search?q=site:valor.globo.com&hl=pt-BR&gl=BR&ceid=BR:pt-419` — universal, mas link é redirect e sem dek.
4. Bing News RSS.
5. Só então HTML (último recurso), respeitando `robots`.

## 6. Enriquecimento (implementado — Fase 3)

- **Dek/resumo**: página lida para extrair meta description (standfirst público) + `articleBody` do JSON-LD quando disponível; muro detectado e respeitado (sem insistência). Cache de 7 dias. Por decisão do dono (uso pessoal), não há skip de `/politica/` da Gazeta; o que evita bloqueio é delay + cache + conditional.
- **Regra de exibição**: corpo alimenta só a máquina ( clustering/matching futuros); na tela, description pública ou trecho curto com atribuição + link.
- **Imagem**: sitemaps do Globo/Valor já trazem `image:image/image:loc`.
- **Editoria**: derivada do 1º segmento da URL (`politica`, `economia`, `mundo`…), com guarda contra slug.
- **Tópicos**: entidades (Lula, Flávio, dólar) via NER para os filtros do Ground.news.

## 7. Faseamento

| Fase | Entrega | Esforço | Critério de aceite |
|---|---|---|---|
| **0 — feito** | Coletores RSS+sitemap, 4 fontes integradas | — | `python app.py` lista as 4 e elas aparecem em stories |
| **1** | Cache SQLite + ETag + agendamento 15 min | 0,5 dia | Rodada incremental; sem rebaixar tudo |
| **2** | Enriquecimento de dek (meta description) | 1 dia | ≥80% das matérias com resumo, sem tocar em paywall |
| **3** | Monitoramento: alerta se fonte cair a 0 itens | 0,5 dia | E-mail/log quando endpoint muda |
| **4** | Revisão jurídica + termos de uso do agregador | — | OK para publicação |

## 8. Riscos e mitigação

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Endpoint muda/é desativado | Média | Alto | Fallback Google News + alerta de 0 itens |
| Bloqueio por WAF/rate limit | Média | Médio | UA ASCII, 1 req/ciclo, backoff, cache |
| Paywall / direito autoral | Média | Alto | Só manchete+link+data; revisão jurídica antes de comercializar |
| Robots bloquear IA | Alta | Médio | Não enviar corpo a LLM; classificar por título |
| Sitemap com notícia antiga | Média | Médio | Ordenar por data do nome do arquivo (bug já corrigido na Gazeta) |

## 9. Nota jurídica (não é parecer)

No Brasil, agregar **manchetes + links** é prática consolidada; reproduzir trechos maiores exige cuidado (LDA, art. 46 — direito de citação) e há debate sobre direito conexo de veículos (PL 2338/2023). Para uso pessoal/protótipo o risco é baixo; **antes de lançar comercialmente, revisar termos e, se houver republicação de resumos, licenciar conteúdo**.

## 10. Estado atual

- 27 fontes integradas (20 RSS + 7 via Arc XP/Google News sitemap).
- ~950 artigos → ~72 histórias por rodada.
- **Viés fixo por fonte**, sem análise por matéria e sem custo de tokens (LLM só com `--llm`).
- **Checagens** do G1 Fato ou Fake, da Lupa (500 mais recentes) e do Aos Fatos cruzadas com as manchetes; histórico por fonte como evidência.
- 2ª leva (30/10): SBT e Band via Google News sitemap, R7 via Arc XP (mesmo padrão do Estadão), DW via `/pt-br/news-sitemap.xml`, Veja/IstoÉ/Crusoé via RSS. Fora: Agência Brasil (feed parado em 2023), Congresso em Foco (inacessível), El País Brasil (encerrado 2021). Governança em `CURADORIA_VIES.md` + `tests/test_sources.py`.

## 11. Checagem de fatos (G1 + Lupa)

| Fonte | Endpoint | Uso |
|---|---|---|
| **G1 Fato ou Fake** | `g1.globo.com/rss/g1/fato-ou-fake/` | RSS com 100 itens; veredito no título (`#FAKE`, `#FATO`, `#NÃOÉBEMASSIM`) |
| **Agência Lupa** | `agencialupa.org/wp-json/wp/v2/posts?categories=142` (paginado, 5×100) | API WordPress; categoria *Verificação* (5.700+ itens); veredito no título |
| **Aos Fatos** | Google News RSS `site:aosfatos.org` | 100 itens; veredito no título; links são redirect do Google |

**Extração de veredito:** não há `ClaimReview` nas páginas. O veredito é lido do título e normalizado em `falso`, `verdadeiro`, `enganoso` ou `checagem` (rodada sem veredito único).

**Casamento ("detectar fake news"):** sobreposição de tokens ponderada por IDF, exigindo (a) termo raro em comum — específico da alegação — e (b) força mínima (4+ tokens ou cobertura ≥ 0,5). Isso separa "mesma alegação" de "mesmo assunto". O selo exibido é **“Checagem relacionada”**, nunca “esta matéria é falsa”.

**Avaliar factualidade das fontes:** postura conservadora. Não pontuamos automaticamente um veículo por menção em checagem — a busca textual da Lupa por “O Globo”, por exemplo, retorna checagens que apenas citam a Globo no corpo. Em vez disso:
- a factualidade curada em `sources.yaml` continua sendo o rótulo oficial;
- quando uma matéria do veículo casa com uma checagem, geramos evidência (`N✓` no trilho) e um sinal `revisar` para revisão humana;
- as evidências se acumulam entre rodadas em `state/factcheck_ledger.json`, com dedup por matéria+checagem;
- ausência de checagem **não** significa confiabilidade.

**Limitações:** o corpus é o recorte recente (200 itens); vereditos por título podem errar em casos ambíguos; o casamento é léxico, não semântico.
