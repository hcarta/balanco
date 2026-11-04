# Pautas de capa ↔ feed

## Objetivo

Hoje cada conceito de capa é ligado a **uma** história (o “lead”). O objetivo é
fazer a pauta de capa virar um **elo com todas as histórias do feed daquele
tema**, para dar contexto ao leitor e melhorar a precisão do viés (amostra
maior, menos dependência de uma única matéria).

## Modelo

1. **Pauta → várias histórias**: cada conceito de capa (`FRONT_CONCEPTS`)
   agrega as histórias do feed que tratam do tema.
2. **`front_pautas` no payload**: lista de pautas com `key`, `label`,
   `n_sources`, `best_position`, `story_ids`, `n_stories`, `coverage_total`,
   `lead` e as manchetes de capa (`sources`).
3. **Marcação por história**: `pauta`, `pauta_key` e `pauta_n_stories`.

## Critério de pertença (determinístico, sem LLM)

- **Suporte do conceito**: a história precisa ter ao menos 2 matérias cujo
  título casa com o regex do conceito, e essas matérias precisam ser ≥ 25% do
  cluster (`PAUTA_MIN_ARTS`, `PAUTA_MIN_RATIO`). Uma matéria lateral não
  arrasta o cluster inteiro.
- **Dimensão da pauta** (`PAUTA_REQUIRE`): conceitos largos exigem também a
  dimensão que define o tema. “Trump” sozinho aparece em Irã, Groenlândia e
  jornal; “Eleição EUA / Trump” exige eleição/midterms/senado/congresso.
- **Exclusividade**: cada história pertence a **uma** pauta — a de maior
  suporte. O lead da capa nunca fica fora da própria pauta.
- **Lead**: melhor casamento lexical entre as manchetes de capa e as histórias
  confirmadas no tema; sem casamento, a história com mais matérias no tema.

## Fases

| Fase | Tarefa | Estado |
|---|---|---|
| **P1** | `front_pautas` com `story_ids`; `pauta`/`pauta_n_stories` nas histórias; casamento por suporte do conceito + dimensão da pauta. | **Concluída** |
| **P2** | UI: “veja também nesta pauta (N)” nos 4 slots + filtro por pauta. | **Concluída** |
| **P3** | Viés agregado da pauta (cobertura dedup por grupo, barra e blindspot no nível da pauta). | **Concluída** |
| **P4** | Conceito como rótulo do hub (“Outros ângulos” usa a pauta quando existir). | **Concluída** |

## Chamada e ranking (02/11/2026)

- **Saturação em 5 jornais** (regra 2): `destaque = 0,75·min(jornais/5,1)
  + 0,15·cobertura + 0,10·recência`. O sinal de capa conta **jornais distintos**
  (a posição não rebaixa nenhum jornal). Com esses pesos, 5 jornais sempre ficam
  acima de 3 mesmo com cobertura menor; 4 × 3 ainda pode ser decidido pela
  cobertura.
- **Chamada da pauta**: a manchete de capa mais recente (pelo `updated` da
  história; empate pela posição) + subtítulo quando a capa expõe (Folha, UOL).
  Os 4 slots e o banner exibem a chamada, não o título antigo do cluster.
- Regra 2 também corrigiu "eleições" no plural, que deixava manchetes de
  midterms fora da pauta.

## Contexto para o leitor (P2)

- No destaque, `<details>` “Veja também nesta pauta (N)” lista até 4 histórias
  irmãs; nos 3 slots menores, um link “Veja também nesta pauta (N)”.
- O link filtra o feed (`?pauta=<key>`), mostra o banner da pauta (jornais,
  posições, histórias, cobertura) e “× Sair da pauta” restaura a capa.


- Nos 4 slots, quando `pauta_n_stories > 1`: **“Veja também nesta pauta (N)”**
  com as demais histórias do feed daquele tema.
- Rótulo do destaque: “abre em N de 6 jornais” + “+ N notícias no Balanço”.
- Clicar na pauta filtra o feed por aquele conceito.

## Precisão do viés (P3)

- `front_pautas[]` traz `counts`, `pct`, `avg_bias`, `blindspot`, `n_groups` e
  `n_articles`: cobertura somada de todas as histórias da pauta, com **uma
  entrada por grupo editorial** (a média das matérias do grupo na pauta).
- O banner da pauta exibe a barra “Viés da pauta” e o blindspot agregado.


- **Viés agregado da pauta**: somar a cobertura de todas as histórias da pauta,
  deduplicando por grupo editorial, e exibir a barra “da pauta”.
- **Blindspot no nível da pauta**: se, somando todas as histórias, um lado está
  ausente, marcar o blindspot da pauta.
- **Posição na capa** pesa no `destaque`, mas **não** na barra de viés (que
  continua factual, por fonte).

## Conceito como rótulo do hub (P4)

- Histórias de uma pauta com 2+ histórias recebem `hub` com
  `key="pauta:<key>"`, `label` do conceito e `size=n_stories`.
- “Outros ângulos desta pauta · <conceito>” passa a listar as histórias do
  tema; o hub por entidade continua como fallback fora das pautas e nas
  pautas de uma história só.

## Lexicon: normalização e variantes (02/11/2026)

- `sing_pt`/`norm_tokens`: acento + singularização leve, usadas **só** no
  casamento de conceitos/pautas (o cluster mantém o token original). Resolve
  “eleições/eleição”, “aviões/avião”, “militares/militar”, “juros/juro”.
- `FRONT_CONCEPT_TERMS`: âncoras de paráfrase por pauta (“meio de mandato”,
  “voto antecipado”, “casa rosada”, “acidente aéreo”…), avaliadas sobre os
  tokens normalizados.
- `tests/test_conceitos_variantes.py`: matriz de positivos (plural/paráfrase)
  e negativos por conceito. Uma mudança no lexicon que quebre uma variante
  falha no CI — não depende de correção reativa.

## Riscos

- **Sobre-agregação**: conceitos largos podem juntar assuntos diferentes.
  Mitigação: suporte mínimo + `PAUTA_REQUIRE` + revisão periódica do lexicon.
- **Viés agregado ≠ viés da história**: a barra da pauta é contexto, não
  substitui a barra da história. Rotular claramente.
- **Custo**: O(conceitos × histórias × matérias) por rodada, desprezível.
