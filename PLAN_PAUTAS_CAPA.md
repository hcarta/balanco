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
| **P2** | UI: “veja também nesta pauta (N)” nos 4 slots + filtro por pauta. | Pendente |
| **P3** | Viés agregado da pauta (cobertura dedup por grupo, barra e blindspot no nível da pauta). | Pendente |
| **P4** | Conceito como rótulo do hub (“Outros ângulos” usa a pauta quando existir). | Pendente |

## Contexto para o leitor (P2)

- Nos 4 slots, quando `pauta_n_stories > 1`: **“Veja também nesta pauta (N)”**
  com as demais histórias do feed daquele tema.
- Rótulo do destaque: “abre em N de 6 jornais” + “+ N notícias no Balanço”.
- Clicar na pauta filtra o feed por aquele conceito.

## Precisão do viés (P3)

- **Viés agregado da pauta**: somar a cobertura de todas as histórias da pauta,
  deduplicando por grupo editorial, e exibir a barra “da pauta”.
- **Blindspot no nível da pauta**: se, somando todas as histórias, um lado está
  ausente, marcar o blindspot da pauta.
- **Posição na capa** pesa no `destaque`, mas **não** na barra de viés (que
  continua factual, por fonte).

## Riscos

- **Sobre-agregação**: conceitos largos podem juntar assuntos diferentes.
  Mitigação: suporte mínimo + `PAUTA_REQUIRE` + revisão periódica do lexicon.
- **Viés agregado ≠ viés da história**: a barra da pauta é contexto, não
  substitui a barra da história. Rotular claramente.
- **Custo**: O(conceitos × histórias × matérias) por rodada, desprezível.
