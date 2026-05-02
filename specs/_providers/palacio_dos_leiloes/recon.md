# palacio_dos_leiloes

Provider operado por leiloeiros da família **Melo Ferreira** em Belo
Horizonte/MG (5 sites_in_provider que apontam todos para o mesmo
domínio: Rafaela, Izabella, Heliana, Cristiano e Rogério).

URL: https://www.palaciodosleiloes.com.br/site/

---

## Tech stack & rendering

- Backend: PHP custom (sem CMS reconhecível). Endpoints: `index.php`,
  `leilao.php`, `lotem.php`, `editais.php`, `produtos.php`,
  `lance_online.php` (gateado por hash + login).
- Frontend: jQuery 3.7.1 + Bootstrap 4.6 + máscaras de input. Templates
  servidos em `iso-8859-1` (latin-1); requer decode explícito.
- Renderização: **dinâmica via XHR**, mas API não-JSON. O HTML inicial
  de `leilao.php` traz a moldura (filtros, formulário, `<div id="div_lotes">`
  vazio) e jQuery POSTa para `camada_ajax/coluna_esquerda_m.php` com
  diferentes valores de `opcao=` (listar_lote, carregar_categoria,
  carregar_leilao, etc.). A resposta é **HTML fragment**, não JSON.
- `requires_playwright: false` — endpoint AJAX aceita POST sem cookie de
  sessão e responde corretamente. Verificado com curl direto.
- robots.txt permissivo (`Allow: /`); apenas `/documents/` bloqueado.
- Sitemap: 1392 URLs (1118 lotes + 274 leilões), todos ativos.

## Listing ativa

URL canônica: `leilao.php?leilao_pesquisa={id}` para uma audiência
específica, ou `produtos.php` (que na verdade é catálogo de **prêmios**
do programa de fidelidade — não é catálogo de leilão).

API real (descoberta via `camada_ajax/coluna_esquerda_m.js` +
`/classes_javascript/funcoes.js::include()`):

```
POST /site/camada_ajax/coluna_esquerda_m.php?quebra=<rand>
Content-Type: application/x-www-form-urlencoded
Encoding: iso-8859-1
Body: opcao=listar_lote
      &categoria_pesquisa=
      &leilao_pesquisa={id}
      &paginacao={offset}     (passos de 8)
      &total_paginas=1
      &tipo_exibicao=grid
      &somente_pesquisa=0
      &e_categoria=0&e_leilao=1...
```

Cada `opcao=` retorna um snippet HTML diferente, todos para serem
inseridos em divs específicos:
- `listar_lote` → `<div id="div_lotes">` (cards dos lotes)
- `carregar_leilao` → `<div id="campo_leilao_pesquisa">` (lista de
  leilões/checkboxes)
- `carregar_categoria` → idem para Categoria
- ... 11 opções no total

## Listing encerrada

**NÃO EXISTE PUBLICAMENTE.**

Investigação detalhada:

| Tentativa | Resultado |
|-----------|-----------|
| `?status=encerrado` etc. | sem efeito (filtro não existe na API) |
| `leilao_pesquisa=8333` (id <8334, mais antigo conhecido) | resposta 1009 bytes "Desculpe, não foi possível localizar" |
| `leilao_pesquisa=8000`, `7000` | mesma resposta vazia |
| `lotem.php?cl=1514551` (lote arrematado) | retorna 44KB mas todo o miolo é substituído por: *"Este lote já foi arrematado! Mas não se preocupe, temos muitas opções incríveis esperando por você."* — zero dados estruturados |
| Aba "histórico" no menu | inexistente |
| `editais.php` | só PDFs prosaicos de editais antigos |

**Conclusão:** o provider purga toda informação estruturada de lotes
encerrados; resta apenas badge "arrematado" sem valor, sem timestamp,
sem bidder. Histórico de lances é gateado por login mesmo durante o
leilão. Reproduzível e idempotente — não há rota legítima.

## Pilot lot escolhido

**NENHUM.** Causa raíz inviabiliza a Etapa 5 do `pilot-extraction-protocol`:

> O catálogo público do `palaciodosleiloes.com.br` **não inclui imóveis**.
>
> Verificado via `camada_ajax/coluna_esquerda_m.php` com
> `opcao=carregar_categoria`: as únicas categorias publicadas são
> **Automovel (1)** com 378 lotes, **Eletro (15)** com 739 lotes, e
> **Maquinario (2)** com 1 lote. Total 1118 — bate com `lotem.php` no
> sitemap. Pesquisa textual `txt_pesquisa_lote=imovel`, `apartamento`,
> `casa` retorna "Desculpe, não foi possível localizar a oferta".

Edital "EDITAL DE CONSOLIDAÇÃO DE PROPRIEDADE - LEILÃO PÚBLICO N
0098/0224 CPA/RE" aparece em `/editais.php` (PDF), mas é **leilão
operado pela CAIXA Econômica** com o leiloeiro do Palácio como agente —
o catálogo digital de lotes desses leilões fica em
`venda-imoveis.caixa.gov.br`, não aqui.

Score `real_estate_score=13.1` no `site_analysis_row` foi inflado por
keywords genéricos no header/footer/PDFs de editais; não reflete o
catálogo digital real.

## Gotchas

1. **Encoding latin-1.** Toda resposta (HTML inicial e fragments AJAX)
   é `iso-8859-1`. `httpx` decodifica errado por padrão; abrir como
   `errors='replace'` ou `encoding='latin-1'` explicitamente.
2. **`?quebra=<random>` cache-buster obrigatório.** O JS embute um
   `Math.random()` em todo POST; sem ele, alguns browsers cacheariam.
   Sem cookies persistentes, não verificado se gocache (CDN nginx) bate;
   por segurança, manter o param.
3. **Header `encoding: iso-8859-1`** customizado no `.setRequestHeader`.
   Não é header padrão HTTP; não obrigatório no curl (testado sem ele
   e funcionou).
4. **`leilao.php?leilao_pesquisa={qualquer_int}`** sempre retorna 200 +
   mesma shell de 34KB. Validade do ID só é verificável fazendo o POST
   AJAX subsequente.
5. **Agrupamento de leiloeiros:** os 5 nomes em `sites_in_provider`
   compartilham o domínio mas o site não atribui lote a leiloeiro nem
   no listing nem no detalhe — quem assina é "Palácio dos Leilões"
   institucionalmente. Para popular `core.auctioneer`, a Fase 2 vai
   precisar parsear o PDF do edital de cada leilão.

## Decisões e limitações

- **Pilot inviável → falha registrada honesta.** Conforme
  `pilot-extraction-protocol §4` e exemplo `cassiano`: prefer-se
  documentar limitação a forjar item.
- `pilot_item.json` **não foi escrito** — não há lote de imóvel
  arrematado disponível para extrair. Escrever um item de
  veículo/eletrodoméstico seria fora de escopo (CLAUDE.md "Schema do
  Item (Property)").
- `validation.json` foi escrito manualmente refletindo `passed_hard:
  false` com motivo "no_real_estate_in_catalog".
- `selectors.yaml` foi preenchido com o **contrato arquitetural** do
  endpoint AJAX descoberto, para que, caso o provider reabra o canal
  Imóveis, o spider de produção tenha o ponto de partida pronto.
- `pilot_listing.html` = home (`index.php`) e `pilot_source.html` =
  exemplo `lotem.php?cl=1514551` (lote já arrematado) — comprova
  empiricamente o estado terminal "Este lote já foi arrematado!".
- Provider é **multi-leiloeiro single-tenant**: 5 leiloeiros físicos,
  um único site. Para o pipeline, sugere-se mapear `auctioneer_slug`
  ao agente que assina cada edital (campo `cod_comitente` do form
  `frm_pesquisa_lote` pode ajudar — não testado).

### Recomendação para o orquestrador

Tratar `palacio_dos_leiloes` como **out-of-scope** para a Fase 1 do
`todoleilao-scraper`. Reavaliar trimestralmente:
1. `GET /site/leilao.php` + POST `opcao=carregar_categoria` → checar
   se a lista volta a incluir uma categoria contendo "Imóv" ou similar.
2. Se sim, retomar o recon a partir deste documento (selectors.yaml já
   tem a API mapeada).
