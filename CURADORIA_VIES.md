# Curadoria de viés — como cada veículo é posicionado

> O Balanço usa **viés fixo por publicação** (como o Ground.news avalia o veículo, não a matéria). Sem AllSides/MBFC no Brasil, a tabela é curadoria manual. Este documento registra os critérios, a posição atual de cada fonte e o histórico de mudanças. Revisão trimestral (ver §4).

## 1. Escala (contexto brasileiro)

| Valor | Rótulo | O que significa na prática |
|---|---|---|
| -2.0 | Extrema-esquerda | Militância explícita pró-governo Lula/esquerda; demoniza a direita como bloco |
| -1.5 – -1.0 | Esquerda | Enquadramento sistematicamente favorável à esquerda/progressismo; crítica seletiva à direita |
| -0.5 – -0.3 | Centro-esquerda | Factual, mas com seleção de pauta e enquadramento levemente pró-esquerda |
| -0.2 – +0.2 | Centro | Factual, múltiplos lados; sem loaded words sistemáticas |
| +0.3 – +0.5 | Centro-direita | Factual, mas com seleção de pauta e enquadramento levemente pró-direita/mercado |
| +1.0 – +1.5 | Direita | Enquadramento sistematicamente favorável à direita/conservadorismo; crítica seletiva à esquerda |
| +2.0 | Extrema-direita | Militância explícita pró-Bolsonaro/direita; demoniza a esquerda como bloco |

**Bucket da interface:** ≤ -0.5 = Esquerda · ≥ +0.5 = Direita · resto = Centro.

## 2. Posições atuais (28 fontes, 30/10/2026)

| Fonte | Viés | Por quê (1 linha) |
|---|---|---|
| G1 | 0.0 | Hard news do maior grupo; factual, sem linha editorial marcada |
| Folha de S.Paulo | -0.3 | Liberal-progressista histórica; crítica a ambos os polos, mais dura com a direita |
| UOL Notícias | -0.2 | Segue a linha Folha (mesmo grupo), com colunismo diverso |
| CNN Brasil | +0.1 | Licença CNN; factual, leve ênfase pró-mercado |
| BBC Brasil | -0.2 | Serviço público britânico; progressista em costumes, factual |
| Poder360 | 0.0 | Cobertura de poder seca, sem linha detectável |
| Metrópoles | 0.0 | Factual e policialesco; sem linha partidária clara |
| Terra | 0.0 | Agregador/telefônica; factual, sem linha |
| Nexo Jornal | -0.4 | Explicativo progressista; seleção de pauta à esquerda |
| Revista piauí | -0.5 | Longform liberal-progressista; crítica contumaz à direita |
| InfoMoney | +0.2 | Finanças; enquadramento pró-mercado por natureza da editoria |
| Estadão | -0.1 | Liberal-conservador histórico, mas com crítica real a Bolsonaro; centro |
| O Globo | +0.1 | Liberal; factual, leve ênfase institucional pró-mercado |
| Valor Econômico | +0.3 | Finanças; pró-mercado explícito, factual de alto padrão |
| Brasil 247 | -1.4 | Partidário pró-Lula/governo; linguagem militante frequente |
| Diário do Centro do Mundo | -1.5 | Partidário pró-esquerda; tom militante |
| CartaCapital | -1.2 | Esquerda assumida; crítica sistemática à direita e ao mercado |
| Jovem Pan | +1.4 | Partidária pró-Bolsonaro/direita; linguagem militante frequente |
| Revista Oeste | +1.6 | Direita assumida; linha editorial abertamente conservadora |
| Gazeta do Povo | +1.2 | Direita curitibana; conservadora em costumes e mercado |
| Agência Brasil | — (pendente) | Feed RSS parado desde 2023; sitemap sem namespace de notícias. Revisitar se publicarem feed vivo |
| SBT News | 0.0 | Popular, factual; sem linha partidária detectável |
| R7 | +0.5 | Grupo Record (Edir Macedo); conservadora em costumes, pró-governos de direita |
| Band | 0.0 | Comercial neutra; jornalismo factual sem linha marcada |
| DW Brasil | 0.0 | Serviço público alemão; factual, padrão internacional |
| Veja | +0.5 | Liberal-conservadora; historicamente anti-PT |
| IstoÉ | 0.0 | Popular-sensacionalista; sem linha partidária consistente |
| Crusoé | +1.0 | Grupo O Antagonista; liberal-conservadora, anti-PT |

## 3. Processo de decisão

1. **Proposta**: qualquer mudança de viés vem com 3–5 manchetes-exemplo que a sustentem.
2. **Evidência**: `state/factcheck_ledger.json` (padrão de checagens), amostragem de 20 manchetes recentes, comparação com a cobertura dos pares no Balanço.
3. **Registro**: toda mudança entra em `state/vies_changelog.md` com data, antes/depois e motivo.
4. **Vedações**: viés nunca muda por causa de UMA matéria; nunca muda automaticamente por checagem (o ledger é evidência, não sentença).

## 4. Revisão trimestral

A cada 3 meses, reavaliar 3–5 fontes, priorizando: (a) `revisar=true` no ledger, (b) fontes novas da última leva, (c) reclamações documentadas. Próxima revisão: **jan/2027**.
