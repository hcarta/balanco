# Extração das capas — estratégia (O Globo, Estadão, Folha, G1, UOL, CNN)

## Problema

Seletores por classe hasheada (Estadão) e por lista de links (UOL) quebram
quando o site muda o HTML ou o módulo principal. Pior: o filtro de URL
(`/colunas/`, `/opiniao/`) pode descartar justamente a manchete principal,
quando ela é uma coluna — foi o caso do “Smart Sampa” na UOL.

## Estratégia

1. **Contêiner semântico antes de classe**
   - O Globo: `a.container-sete-destaques__url`
   - Estadão: blocos `manchete` / `news-block` e `h2.headline`
   - UOL: `article.headlineMain`, `article.headlineSub`,
     `article.headlineHorizontal(Brand)`, `article.headlinePhoto`
   - Folha: `.col--md-3-4` (mantido)
   - G1: `.feed-post-body-title`
   - CNN: âncoras com heading (mantido)

2. **Filtro ciente do módulo**
   - Opinião/coluna é descartada por URL **exceto** quando o item está no
     módulo principal (`allow_main` na UOL). Assim a manchete-coluna entra,
     mas colunas secundárias continuam fora.

3. **Fallback e retry**
   - Se o seletor principal não achar nada, o extrator cai para “âncoras com
     heading”, mantendo os mesmos filtros.
   - Uma segunda tentativa após 1 s; se continuar vazio, grava
     `[aviso] capa <fonte>: 0 manchetes extraídas` no log.

4. **Qualidade e ordem**
   - título ≥ 25 caracteres, dedup, link fora da home, ordem da página;
   - filtros de serviço/esporte/entretenimento por título e URL;
   - `main` marca o item de destaque para a exceção do item 2.

5. **Monitoramento**
   - `[3b/4] capas` mostra a contagem por jornal em toda rodada;
   - `front_unmatched` mostra o que não casou com pauta;
   - duas rodadas seguidas com < 2 manchetes numa fonte = revisar seletor.

6. **Testes**
   - fixture por seletor (sem rede);
   - teste da exceção “coluna na manchete principal”;
   - teste do fallback quando o seletor some.

## Limites conhecidos

- Páginas com conteúdo personalizado/JS (ex.: itens abaixo do fold) podem não
  vir no HTML servido; nesse caso o fallback não resolve.
- Estadão ainda mistura opinião/cultura na lista; os filtros cortam o óbvio,
  mas revisão manual periódica continua necessária.
