# Balanço — Ground.news brasileiro (MVP)
Agregador de notícias BR que mostra **todos os lados da mesma história**: barra de viés esquerda/centro/direita, comparação lado a lado e detector de blindspots.

Inspirado no [Ground.news](https://ground.news/).

## Como funciona
1. `sources.yaml` — fontes + metadados (viés-base, propriedade, factualidade) e o `fetcher` (`rss` ou `sitemap`).
2. `collectors.py` — adaptadores de coleta: RSS/Atom e Google News sitemap (com resolução de índice por data).
3. `app.py` — agrupa notícias iguais (TF-IDF + cosseno), aplica **viés fixo da fonte**, gera `docs/data.json`.
4. `docs/index.html` — interface estática (sem build): feed, barra de viés, comparação, blindspots.
5. `classify_llm.py` — classificação por IA **opcional** (só com `--llm`).
6. `factcheck.py` — checagens do **G1 Fato ou Fake** e da **Agência Lupa** (vereditos + links).

## Interface
Estética editorial inspirada no **The Atlantic** (serifada, filetes finos, respiro, pequenos caps) com a leitura de viés do **Ground.news** (barra Esq/Centro/Dir).

- **Masthead + destaque**: a história mais repercutida entre os veículos abre a edição.
- **Hero lateral**: as 3 mais repercutidas no centro de alta factualidade, ao lado do destaque.
- **Barra de viés** em cada história, com percentuais por **grupos editoriais independentes** (G1 + O Globo + Valor = 1 voz; a etiqueta mostra coberturas · grupos). Só **hard news, análise e explicativo** contam; opinião/longform/podcast/vídeo aparecem como enquadramento.
- **Comparar os lados**: painel em 3 colunas (esquerda/centro/direita) com veículo, factualidade e propriedade.
- **Leituras da semana**: página própria no menu **📚 Leituras** (e card no rail): índice de 10 dias das fontes longform (piauí, Nexo, Pública, Intercept, Repórter Brasil, Crusoé), máx. 2 por fonte, em **2 colunas** com thumb quando o feed oferece imagem.
- **Aprofunde-se**: duas relações — “Análise desta pauta” (mesmo fato, até 14 dias) e “Para entender melhor” (pano de fundo, até 120 dias, exige 2+ entidades específicas); máx. 1 por fonte e 3 por história.
- **Quem deu primeiro**: linha do tempo por veículo no painel de comparação, ordenada pela **publicação** (`published`; `first_seen` como fallback).
- **Comparar os lados por veículo**: uma manchete principal por veículo; os demais artigos ficam em “Mais artigos deste veículo” (details). O `updated` da história usa só cobertura — opinião/vídeo não rejuvenesce a notícia.
- **Lá fora**: peças internacionais agrupadas por evento (cluster + entidade/número), com número de veículos e fontes no cartão; casamento por entidade traduzida, número e conceito.
- **Agrupamento com âncora de entidade**: dois títulos só viram a mesma história se compartilharem um nome próprio específico **e** conteúdo além do nome, ou forem quase-duplicatas. Vocabulário de tema ("eleição presidencial", "menor nível") não funde fatos distintos — foi o que ligava a eleição na Bulgária ao Flávio Bolsonaro.
- **Trilho lateral**: checagens recentes, blindspots do dia, leituras da semana e fontes monitoradas (com viés).
- **Pautas (Outros ângulos)**: lugar não é pauta — estado/cidade fica em `HUB_STOP_GEO` (“Mato Grosso” juntava violência em MS, soja e TCE).
- **Pautas (Outros ângulos)**: a história só entra na pauta de um nome próprio se ele está na manchete e em pelo menos 2 títulos; menção lateral ("Democratas cobram Trump…" citando Flávio) não conta. Prenome sozinho vale como alias ("Flávio"); sobrenome não ("Bolsonaro" é o Jair).
- **Seções recolhíveis**: “Aprofunde-se”, “Lá fora”, “Outros ângulos desta pauta” e “Também apurado nesta história” são `<details>` fechados por padrão, com contador no cabeçalho.
- **Aba Metodologia** na navegação + página "Como lemos" com todos os critérios (viés, factualidade, blindspot, agrupamento, checagens, enriquecimento).
- **Filtros**: todas, blindspots, + esquerda/+ direita, mais divididas + busca. Ao filtrar ou buscar, o destaque é ocultado para o resultado começar no topo.
- **Link direto** para uma história: `index.html?story=h...` (IDs estáveis) ou alias antigo `?story=sNNN` / `#...`.
- Responsivo (mobile com pílulas roláveis e busca fixa).

## Uso rápido (viés fixo por fonte — padrão)
```bash
pip install -r requirements.txt
python app.py
open docs/index.html
# ou: python -m http.server -d docs 8000
```

### Opcional: embeddings semânticos

O `--embed` usa o MiniLM multilíngue para complementar as conexões de longform e internacionais. No Aprofunde-se, o scorer híbrido (embedding + entidade-idf + recência) admite e ordena peças sob `--embed`, com âncora lexical obrigatória; sem `--embed`, vale a regra de entidade. No CI, o backend é **ONNX/fastembed** (`requirements-embed.txt`, ~220 MB, sem torch) com o modelo em cache; localmente, se `fastembed` não estiver instalado, cai para `sentence_transformers`. Sem modelo, tudo volta ao TF-IDF/regras lexicais.

O agrupamento usa embeddings apenas com `--embed-cluster` (experimental): a coerência A-4 ainda não está calibrada para isso, e a versão anterior criou uma história com 645 coberturas.

### Testes (rode antes de mudar o núcleo)
```bash
python -m pytest tests/ -q   # 113 testes: coletores, vereditos, cache, matching, conexões, fuso, ids
```

O viés vem de `sources.yaml` (nível de **publicação**) e é o mesmo para toda matéria daquela fonte. **Não há chamada de IA nem custo por artigo.** Esporte (`esportes`, `futebol`) e conteúdo de serviço (loteria, horóscopo, previsão do tempo, calendário de pagamento/benefício) ficam fora da edição por decisão editorial. Evento meteorológico com impacto (alagamento, desabrigados, sem luz) continua entrando: o filtro pega previsão e alerta, não a notícia.

```bash
python app.py --fresh      # ignora o cache (baixa tudo de novo)
python app.py --window 24   # só artigos das últimas 24 h
python app.py --no-checks   # pula a camada de checagem
```

### Opcional: viés por artigo com IA
Só quando quiser, com custo de tokens explícito:
```bash
cp .env.example .env
export OPENAI_API_KEY="sk-..."
python app.py --llm
```
Cada artigo é então classificado (-2=extrema-esq … +2=extrema-dir). Sem a flag, o LLM nunca é chamado.

### Enriquecimento (`--body`, opt-in)
Coleta meta description + corpo público (JSON-LD `articleBody` → `<article>`), com cache de 7 dias, delay e teto por rodada. Detecta muro e não insiste. Regra: **corpo para máquina, curto para humano** — na tela só description ou trecho curto com link. Robots de editoria ignorados por decisão do dono (uso pessoal); o que evita bloqueio é delay + cache + conditional.
```bash
python app.py --body --body-cap 40
```
Medido em 30/10: 39 resumos preenchidos, 36 com muro (Valor/Globo/Folha/Estadão), 3 corpos íntegros (Gazeta serve `articleBody` no JSON-LD).

## Checagem de fatos
O app coleta automaticamente **G1 Fato ou Fake** (RSS, 100), **Agência Lupa** (API, até 500 mais recentes de 5.700+ na categoria *Verificação*) e **Aos Fatos** (Google News RSS, 100), extrai o veredito do título e cruza com as manchetes.

- **Selo ⚑ Checagem** aparece quando a alegação da checagem coincide com a história/matéria. É uma checagem *relacionada*, não um veredito sobre a matéria. Passe o mouse para ver os termos em comum.
- **🔍 Verificar este tema** aparece quando não há checagem ligada — abre a busca do tema na Lupa.
- **Card “Checagens recentes”** lista as últimas verificações dos três veículos.
- **Histórico por fonte**: quando uma matéria do veículo casa com uma checagem, o trilho mostra `N✓` ao lado do nome. As evidências são **acumuladas entre execuções** em `state/factcheck_ledger.json` (dedup por matéria+checagem) e servem para revisão humana — não alteram automaticamente a factualidade curada da fonte.
- Casamento conservador: sobreposição ponderada por raridade (IDF), exigindo termo específico da alegação. Evita confundir “mesmo assunto” com “mesma alegação”.
- Para desligar: `python app.py --no-checks`.

## Fontes (36, testadas em 30–31/10/2026)
Mainstream/centro: G1, Folha, UOL, CNN Brasil, BBC Brasil, Poder360, Metrópoles, Terra, Nexo, InfoMoney, **Estadão**, **O Globo**, **Valor Econômico**, **SBT News**, **Band**, **DW Brasil**, **IstoÉ**.
Centro-esquerda: **Revista piauí**.
Esquerda: Brasil 247, Diário do Centro do Mundo, CartaCapital, **Agência Pública**, **The Intercept Brasil**, **Repórter Brasil**.
Direita: Jovem Pan, Revista Oeste, **Gazeta do Povo**, **R7**, **Veja**, **Crusoé**.
Internacionais (só em "🌍 Lá fora", fora das barras): **Al Jazeera English**, **Fox News**, **New York Times (World + Tecnologia)**, **The Guardian**, **BBC World**.

Fora por ora: **Agência Brasil** (feed parado desde 2023), **Congresso em Foco** (inacessível daqui), **El País Brasil** (encerrado em 2021).

### Fontes sem RSS público
Estadão, O Globo, Valor e Gazeta bloqueiam RSS, mas expõem caminhos machine-readable sancionados que o projeto já usa:
- **Estadão** → RSS Arc XP (`/arc/outboundfeeds/rss/?outputType=xml`)
- **O Globo / Valor** → Google News sitemap (`/sitemap/<veículo>/news.xml`)
- **Gazeta** → índice `sitemap.xml` → `*-gnews.xml`

Coletamos **apenas manchete, link, data e editoria** (sem corpo, sem paywall). A estratégia completa, com diagnóstico, fallbacks, riscos e faseamento, está em [`ESTRATEGIA_AGREGACAO.md`](ESTRATEGIA_AGREGACAO.md).

## Publicação automática (GitHub Actions — Via B)

O workflow `.github/workflows/collect.yml` roda `python app.py` a cada 30 min e publica `docs/` via **GitHub Pages (artefato)**. `data.json` e `feed.xml` deixam de ser versionados a cada rodada; o cache (`state/cache.db` + `state/factcheck_ledger.json`) circula por `actions/cache`; o arquivo diário e o health/ledger são commitados **uma vez por dia** (marcador `state/.last_commit_day`).

```bash
# 1. criar o repo no GitHub (público: Actions ilimitado)
gh repo create balanco --public --source=. --push
# ou manual: github.com/new → git remote add origin … && git push -u origin main

# 2. ativar o site: Settings → Pages → Build and deployment → Source: GitHub Actions
#    (enquanto estiver em "Deploy from branch", o workflow faz fallback e
#     mantém o commit antigo para o site não parar)
# 3. pronto: a cada 30 min a edição se atualiza sozinha
# manual: aba Actions → "Coleta Balanço" → Run workflow
```

Notas:
- Cron do Actions pode atrasar alguns minutos; `concurrency` evita rodadas sobrepostas.
- Se o Pages Actions falhar (por exemplo, a origem ainda está em “Deploy from branch”), o fallback commita `data.json`, `feed.xml`, `arquivo`, `health` e ledger, e o site continua no ar.
- Se o cache do Actions vier vazio, o workflow semeia `state/cache.db` a partir de `state/seed.db.gz` (versionado, só para cold start).
- `state/health.json` e o ledger são commitados no máximo uma vez por dia; o cache guarda o ledger entre rodadas.
- Logs de cada rodada ficam na aba Actions (retention padrão 90 dias).

## Limitações honestas vs Ground.news
- Ground usa AllSides/AdFontes/MBFC (só EUA). No Brasil não existe equivalente — aqui o viés é **fixo por publicação** (curadoria manual em `sources.yaml`), **não por artigo isolado**.
- Clustering aqui é TF-IDF simples (Ground usa ML + curadoria). Precisa de ajuste de threshold.
- Factualidade/propriedade são tabeladas manualmente em `sources.yaml` (Ground pesquisa 2000+ outlets).

## Próximos passos
O roteiro completo, com fases, esforço estimado e critérios de aceite, está em [`PLANO.md`](PLANO.md). Resumo do que falta: newsletter (pende provedor de envio), domínio + analytics + SEO, jurídico, modelo de negócio. Opcionais: alerta por e-mail, matching semântico, corpos em cache no clustering, revisão trimestral de viés (jan/2027).
