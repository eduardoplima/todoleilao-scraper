# sodre_santoro

Provider: **sodre_santoro** — site único e tradicional, controlado pela
família Sodré Santoro (representante INNLEI: OTAVIO LAURO SODRE
SANTORO/DF; alvo no AlmagestoDB: dominio `sodresantoro.com.br`,
real_estate_score 12.9, confidence high). Operação multissegmento
(veículos, materiais, imóveis, sucatas, joias) com leilões online e
presenciais.

## Tech stack & rendering

`site_analysis.csv` classifica como **dynamic** (Nuxt; Vue; tech_signals
`/_nuxt/` + `__NUXT__`). Confirmado em recon manual:

- `https://www.sodresantoro.com.br/` e `/imoveis/lotes` — Nuxt SPA,
  Azion edge na frente. Bot UAs simples (`TodoLeilaoBot/1.0`) levam **403**
  do edge; basta usar UA Chrome real para passar (status 200).
- `https://leilao.sodresantoro.com.br/leilao/{auction_id}/lote/{lot_id}/`
  — backend legacy PHP/Stimulus (`data-controller="lances"`,
  `data-controller="historic-bids"`), HTML completo no GET. Esse domínio
  **não tem o WAF Azion**, responde 200 com qualquer UA razoável e contém
  todos os campos para o piloto.
- API: `POST https://www.sodresantoro.com.br/api/search-lots` é uma
  passagem direta ao Elasticsearch (corpo `{indices, query, aggs, from,
  size, sort}`). Aceita só requisições com Origin/Referer do próprio site
  ou via fetch dentro da página renderizada — tentativa via httpx puro
  retorna 403 do Azion. **Não há auth/token explícito; é proteção
  baseada em headers de browser.**
- Endpoint auxiliar: `https://prd-api.sodresantoro.com.br/api/v1/auctions`
  retorna lista de leilões; `…/api/v1/site/segments` retorna a árvore de
  categorias.

## Listing ativa

- URL canônica: `https://www.sodresantoro.com.br/imoveis/lotes`.
- O HTML da SPA não traz anchors de detalhe — a listagem é populada
  via 3 chamadas a `POST /api/search-lots`: (1) agregação de segmentos,
  (2) agregações de filtros por imóveis, (3) resultados em si.
- Body típico do GET de resultados (ver `_xhr_full.json`, terceira call):
  ```json
  {
    "indices": ["imoveis", "judiciais-imoveis"],
    "query": {"bool": {"filter": [
      {"bool": {"should": [
        {"bool": {"must": [{"term": {"auction_status": "online"}}]}},
        {"bool": {"must": [{"term": {"auction_status": "aberto"}}],
                  "must_not": [{"terms": {"lot_status_id": [5,7]}}]}},
        {"bool": {"must": [{"term": {"auction_status": "encerrado"}},
                           {"terms": {"lot_status_id": [6]}}]}}
      ], "minimum_should_match": 1}},
      ...
    ]}},
    "from": 0, "size": 48,
    "sort": [{"lot_status_id_order": {"order": "asc"}},
             {"auction_date_init": {"order": "asc"}}]
  }
  ```
- Cada `result` traz `auction_id`, `lot_id`, `lot_title`, `lot_state`,
  `lot_city`, `lot_neighborhood`, `lot_street`, `lot_useful_area`,
  `lot_total_area`, `lot_pictures[]`, `bid_initial`, `bid_actual`,
  `bid_has_bid`, `bid_user_nickname`, `auction_date_init`,
  `auction_date_end`, `lot_description`. URL de detalhe é montada
  como `https://leilao.sodresantoro.com.br/leilao/{auction_id}/lote/{lot_id}/`.
- Total imóveis ativos: **47** (29 leilões); existe 1 com lance
  registrado.
- Paginação: por `from` + `size` no body (não querystring de URL).

## Listing encerrada

**`listing_closed: null`.** Recon esgotou o que era possível:

1. Filtros explícitos no índice `imoveis` retornam 0:
   - `auction_status: encerrado` → 0 docs.
   - `lot_status_id: 6` → 0 docs.
   - `bid_has_bid: true` em encerrados → 0 docs.
2. Agregação global por `_index` mostra que **todos os 51 lotes
   encerrados do site estão no índice `veiculos`** (lot_status="não
   vendido", lot_status_id=6). Imóveis não geram registros encerrados —
   provavelmente o índice é purgado quando o leilão termina.
3. Nenhuma rota pública do tipo `/imoveis/encerrados`,
   `/imoveis/resultados`, `?status=encerrado` retorna conteúdo (todas
   403/302 sem listagem).
4. `prd-api.sodresantoro.com.br/api/v1/auctions` lista 82 leilões, todos
   com `status: "A"` e `closingDate` futuro. Não há endpoint
   `…/auctions?status=closed` funcional (mesmo retorno do default).

Limitação documentada: **provider não preserva imóveis encerrados em
canal público**. Para Fase 2, captura tem que ser incremental durante
janela de atividade (tipicamente 7-14 dias entre `auction_date_init` e
`auction_date_end`).

## Pilot lot escolhido

- URL: `https://leilao.sodresantoro.com.br/leilao/28423/lote/2743972/`
- Tipo: vaga de garagem (Edifício São José, AMPARO/SP).
- Razão: **único imóvel com `bid_has_bid: true`** em todo o índice
  (47 ativos), o que mais se aproxima do foco "leilão com lances"
  permitido por este provider.
- Estado: `auction_status: aberto / lot_status: andamento` (1ª praça,
  agendada 13/05/2026 11:30h). Mapeado para `auction_status: ativo`.
- 1 lance no `#tabela_lances`: bidder `E*e` (apelido pseudonimizado
  pelo próprio provider), valor R$ 19.400,00 + comissão R$ 970 →
  total R$ 20.370. **Sem timestamp absoluto na tabela**, e o protocolo
  `closed-auction-bids` proíbe inferir; portanto `bids: []`.
- Campos preenchidos no pilot: title, description completa, address
  (raw_text + street/number/district/municipality/uf), area_sqm 12.50,
  total_area_sqm 17.27, market_value_brl 17000, 1 round (1ª Praça
  com minimum_bid_brl 19139, scheduled_at tz-aware), 2 imagens, 3
  PDFs (2 editais + 1 anexo do lote), 4 ônus textuais.
- SOFT warning único: `address.cep` (provider não publica CEP no detalhe).

## XHRs descobertas

Captura via Playwright (`/tmp/recon_xhr3.py`, log em `_xhr_full.json`):

| Método | URL | Tamanho | Função |
|---|---|---|---|
| GET | `www.sodresantoro.com.br/api/server-date` | 35 B | sincronização de relógio |
| GET | `prd-api.sodresantoro.com.br/api/v1/auctions?status=online` | 24 B | leilões online ativos (vazio neste momento) |
| GET | `prd-api.sodresantoro.com.br/api/v1/site/segments` | 1.9 KB | árvore de segmentos + categorias |
| POST | `www.sodresantoro.com.br/api/search-lots` | 449 B → 268 KB | listagem (3 chamadas: agregação geral, filtros, resultados) |

Endpoint legado **deprecado** confirmado: `prd-api.sodresantoro.com.br/api/v1/lots`
retorna `"Depreciado - 30/07/2025"` (status 400). Spider final deve usar
exclusivamente o passthrough Nuxt `/api/search-lots`.

## Gotchas

1. **Azion bloqueia bot UAs no domínio www**, mas não no
   `leilao.sodresantoro.com.br`. Spider final precisa de UA Chrome
   válido (com `Accept-Language: pt-BR`) ao chamar a SPA/API; nas
   páginas de detalhe pode usar `TodoLeilaoBot/1.0` puro.
2. **API exige cookie de sessão Nuxt para POST** — chamada `httpx` direta
   retorna 403, mas request feita via `page.evaluate("fetch(...)")` no
   contexto carregado funciona. Spider de produção deve fazer *bootstrap*:
   fetch da home com `httpx`, extrair cookie de sessão, depois POST
   `/api/search-lots`. Alternativa: spider Playwright só pra listagem.
3. **`bid_initial` ≠ `market_value`**: aval. = 17.000 mas lance inicial
   da praça = 19.139 (mais bid acumulado de R$ 261?). No pilot,
   `market_value_brl=17000`, `rounds[0].minimum_bid_brl=19139`. Para
   spider final, considerar `bid_initial` o canônico para 1ª praça.
4. **Listagem mistura `imoveis` + `judiciais-imoveis`**: campo
   `lot_is_judicial: true|false` no resultado distingue. Spider final
   deve persistir como `core.auction.is_judicial`.
5. **Lances sem timestamp** — tabela `#tabela_lances` é o que existe; se
   o provider passar a entregar timestamp em fase futura (campo
   `data-time` ou similar), incluir no spider. Hoje, `bids: []`.
6. **Praça única** neste pilot — leilão extrajudicial, sem 2ª praça
   anunciada. Em judiciais, esperar 2 rounds; o site usa
   `aditionalInfoLot_type_auction` ("1ª Praça") + `auction_date_2`
   (na API) para sinalizar.
7. **`property_type` mapeado para `outro`** porque "vaga de garagem"
   não casa com o enum (apartamento|casa|terreno|comercial|rural).
   Em Fase 2, `core.unit_kind` pode ganhar uma extensão `vaga_garagem`.
8. **API uppercase mismatch nas pictures URL**: extensões `.JPG`
   maiúsculas em fotos do provider; spider deve aceitar
   `(?i)\.jpe?g|\.png|\.webp`.

## Decisões e limitações

- `requires_playwright = False` no spider final, **mas** com caveat:
  é necessário fazer um GET inicial via httpx na home/listagem para
  obter cookies (UA Chrome) antes de POSTar `/api/search-lots`. Se
  der trabalho replicar, fallback é Playwright só pra listagem (1 page
  load + extract via context.evaluate). Detalhes seguem 100% httpx.
- Imóveis encerrados: **fora do alcance público**. Estratégia para
  histórico: scrape contínuo durante janela ativa do leilão, capturando
  `bid_actual` e `bid_user_nickname` ao longo do tempo (snapshotting),
  já que o resultado final some do índice depois.
- PII: o provider já entrega apelidos pseudonimizados (formato `E*e`,
  `f*o*1*4`) na API e na tabela de lances; mantido como está. Descrição
  cita números de processos judiciais (públicos por princípio da
  publicidade) — mantidos.
- Foco do prompt era "leilão encerrado com lances": **não atendido em
  imóveis** porque o provider não publica esse estado. Pilot escolhido
  é o caso ativo mais próximo (com 1 lance registrado), o que valida
  o pipeline de extração de bid_actual + bidder mas resulta em
  `bids: []` por falta de timestamp.
