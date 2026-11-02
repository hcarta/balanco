# Pautas on-the-fly — agenda diária sem lexicon fixo

## Problema

O `FRONT_CONCEPTS` é um dicionário fixo (13 conceitos / 44 âncoras). Na rodada
atual ele reconheceu 13 de 30 manchetes de capa (43%). Uma pauta nova abre em
3 jornais, mas, como não está no dicionário, não gera `front_score` e **não
entra nos 4 slots**. O fallback por cobertura só atua quando há menos de 4
pautas de capa — quase nunca.

## Princípio

As 6 capas são a fonte da agenda. A pauta deve **emergir do agrupamento das
manchetes do dia**, não de um dicionário. Restrições mantidas: determinístico,
sem LLM por matéria, viés fixo por fonte, ranking explicável.

## Arquitetura alvo

1. **Coleta** (já existe): `fetch_front_page` → ~30 manchetes filtradas por
   `FRONT_SKIP`/`FRONT_SKIP_URL`.
2. **Agrupar manchetes em pautas**: rodar o mesmo cluster de TF-IDF + entidades
   (embeddings opcionais) sobre as manchetes. Cada grupo = uma pauta.
3. **Ligar às histórias do feed**: casar cada manchete com histórias (matcher
   existente) → `story_ids`, cobertura e viés agregado (já implementados).
4. **Chamada** (já existe): manchete mais recente + subtítulo.
5. **Chave estável**: entidade dominante (presente em ≥2 manchetes) ou slug da
   manchete representante; `aliases` preservam links antigos.
6. **Rótulo**: entidade dominante; override humano em `pautas.yaml` quando
   necessário.

## O lexicon vira override, não fonte

`FRONT_CONCEPTS` deixa de decidir *quem entra*. Passa a:

- rotular/renomear pautas emergentes;
- fundir ou separar emergentes mal agrupadas;
- fornecer `PAUTA_REQUIRE` (precisão de pertença);
- manter o rótulo do hub (`P4`).

## Rollout seguro (fases)

| Fase | Tarefa | Aceite |
|---|---|---|
| **0 — mitigação** | `front_unmatched` no payload/log + fallback de destaque para história grande sem pauta. | Pauta nova não some do topo; buraco visível. |
| **1 — sombra** | Computar pautas emergentes em paralelo e logar a concordância com o lexicon. | Métrica diária de taxa de reconhecimento. |
| **2 — primário** | Pautas emergentes viram a fonte dos slots; lexicon vira override. | Pauta nova aparece no topo no dia em que abre. |
| **3 — rótulos** | Rótulo automático por entidade + `pautas.yaml` de override + aliases. | Chave estável entre rodadas. |
| **4 — semântica (opcional)** | Embedding MiniLM como ponte de paráfrase, com eval rotulado e flag. | Recall de paráfrase sem novos falso-positivos. |

## Métricas e aceites

- **Taxa de reconhecimento**: manchetes com pauta / manchetes extraídas. Meta
  crescente por rodada.
- **Estabilidade de chave**: fração de pautas cuja chave se mantém entre
  rodadas consecutivas.
- **Testes de cluster de capa**: fixtures sintéticas com capas que mudam de um
  dia para o outro (pauta que nasce, pauta que morre, pauta que vira sinônimo).

## Riscos e mitigações

- **Chave instável** (URLs mudam): entidade dominante + aliases + teste de
  estabilidade.
- **Sobre/sobre-agrupamento de manchetes**: thresholds do cluster + a guarda de
  entidade/cobertura já calibrada.
- **Rótulo errado**: override humano em `pautas.yaml`.
- **Cluster de capa é pequeno** (~30 docs): TF-IDF basta; embeddings só para
  paráfrase, atrás de flag.
