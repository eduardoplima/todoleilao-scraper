# s4b_digital

Recon arquitetural do **provider `s4b_digital`** — plataforma SaaS de
leilões operada pela S4B Digital / Superbid (`api.s4bdigital.net`,
`offer-query.superbid.net`, `event-query.superbid.net`,
`siteconfigprod.superbid.net`, `static.s4bdigital.net`,
`ms.sbwebservices.net`). 43 leiloeiros do `_input.json`
apontam para esta plataforma; cada um é um **storeId** dentro do
mesmo backend Superbid (portalId=2 ou 15). Sites observados rodam
o mesmo frontend SPA React/Material-UI (`vendor.<hash>.js`,
`bundle.<hash>.js`).

Tenant representativo do `_input.json`: **`npleiloes.com.br`**
(storeId=16147, Josiane Nunes Pinotti, RS).

Tenant escolhido para o piloto: **`eckertleiloes.com.br`**
(storeId=16063, Marciano Mauro Pagliarini, SC). Decisão deliberada:
NP Leilões catalogou apenas inventário PME (Logística Reversa,
Relógios, Informática) no momento da observação — `productType=13`
(Imóveis) tem 0 abertos e 37 "encerrados" no NP, mas todos esses 37
são na verdade **mis-tagged** (`subCategory.description = "Partes &
Peças Carros"`, `"Motocicletas"`, etc.), legacy de catalogação
anterior. Eckert oferece imóveis legítimos com bid history ativo
(165 lances no piloto). O recon arquitetural cobre o **provider**
(infra compartilhada idêntica), e o piloto extrai um leilão
**encerrado com lances** — alvo explícito do prompt de recon.

## Tech stack & rendering

`site_analysis.csv` (linha referente a NP) traz:
`rendering=dynamic`, `tech_stack="jQuery; Superbid"`,
`tech_signals=jquery | superbid | server:cloudflare`,
`static_useful_links=0`, `dynamic_useful_links=140`,
`requires_js_for_listings=True`. Confirmado em todos os 5 tenants
amostrados (NP, Eckert, JMF, Sala de Leilões, Barreto).

- **Frontend**: SPA React + Material-UI (`MuiGrid-root`,
  `MuiTypography-*`, `jss*`/`css-*` classes auto-geradas a cada
  build). HTML inicial tem `0` anchors `/oferta/`/`/lote/` — toda
  listagem é hidratada via XHR. Bundle Webpack estático em
  `./js/vendor.<hash>.js` + `./js/bundle.<hash>.js`. jQuery
  ainda carregado (`jquery-3.6.1.min.js`) para integrações legacy.
- **Tema/branding por tenant**: carregado via
  `https://siteconfigprod.superbid.net/{host}/style.config.json`
  (cores, logo, banner, storeId, portalId). Permite o mesmo
  bundle servir 43+ tenants.
- **Backend (APIs públicas, sem auth)**:
  - `GET offer-query.superbid.net/offers/?filter=stores.id:{storeId}[;product.productType.id:13];searchType={opened|closed}&pageNumber=N&pageSize=30&portalId=[2,15]&requestOrigin=store&locale=pt_BR&orderBy=endDate:asc`
    — listagem; resposta tem `total`, `start`, `limit`, `offers[]`
    (cada item já traz tudo: galeria, descrição, lance inicial,
    auction parent, location lat/lon, productType).
  - `GET offer-query.superbid.net/seo/offers/?filter=id:{offerId};stores.id:{storeId}` — detalhe SEO-friendly.
  - `GET offer-query.superbid.net/categories/?storeId={sid}` —
    productTypes com count por categoria (id=13 é Imóveis,
    confirmado em Eckert/JMF/Barreto).
  - `GET event-query.superbid.net/events/v2/?filter=storeIds:{sid}[;modalityId:[1,4,5,7]]&byPage=marketPlacePage`
    — leilões (eventos) agregados.
  - `GET event-query.superbid.net/submarketplaces/?portalId=[2,15]`
    — taxonomia de submarkets (PME, GOV, JUDICIAL...).
  - `GET smart-schedule-api.superbid.net/event/{auctionId}/lot/{lotNumber}/event-schedules`
    — calendário de praças.
  - `GET banner-api.sbwebservices.net/banner?storeId={sid}` —
    banners promocionais.
- **Backend (APIs auth-only, retornam 401)**:
  - `api.s4bdigital.net/auction-event/offer/{offerId}` — detalhe completo.
  - `api.s4bdigital.net/auction-event/offer/{offerId}/bids` —
    **histórico de lances**. **Crítico para nosso prompt:** bids
    requerem JWT de usuário cadastrado. Anônimos veem apenas o
    agregado: `totalBids` (int), `totalBidders` (int), `hasBids`
    (bool), `winnerBid.currentWinnerLogin` (já ofuscado pelo
    backend, e.g. `"m*****la"`).
  - `api.s4bdigital.net/habilitation/auction-event/auction/{auctionId}/step-config`
    — fluxo de habilitação para lances (KYC).
- **Mídia**:
  - Fotos: `https://ms.sbwebservices.net/photos/{uuid}.jpg`
    (CDN Superbid). Sem variantes; mesmo URL serve thumb e full.
  - Logos: `https://static.s4bdigital.net/logos_empresas/*.png|jpg`
    (filtrar para excluir do `images[]` do bem).
- **CDN/host**: Cloudflare (`server: cloudflare`) com challenge
  passive (`/cdn-cgi/challenge-platform/*`). Sem JS challenge
  bloqueante para `httpx` com User-Agent identificável.
- **Tracking**: Google Ads + GA4 (4 tenants distintos), DoubleClick,
  reCAPTCHA carregado mas não exigido para navegação anônima,
  New Relic Browser, BlipChat widget. **Não relevante** para o
  spider de leitura.
- **robots.txt**: `User-agent: * Allow: / Sitemap: /sitemap.xml`.
  Permissivo para todo o site. Crawl ético com 1.5s delay.

**Conclusão**: `requires_playwright = False` para a Fase 1 e Fase 2
de produção. A SPA é exclusivamente **client-side decorative**
sobre as APIs JSON públicas. Playwright só foi usado durante o
recon para descobrir endpoints; o spider final consome
`offer-query.superbid.net` direto via `httpx`.

## Listing ativa

**URL**: `https://{tenant_host}/?searchType=opened&pageNumber=1&pageSize=30&orderBy=endDate:asc&filter=product.productType.id:13`

Em termos da API (canônica): `GET https://offer-query.superbid.net/offers/?filter=stores.id:{storeId};product.productType.id:13&searchType=opened&pageNumber=N&pageSize=30&portalId=[2,15]&requestOrigin=store&locale=pt_BR&orderBy=endDate:asc`.

Cada item da resposta JSON é um *offer* completo:
- `id` (offerId, chave primária do lote em todo o provider)
- `lotNumber` (1..N dentro de um auction)
- `priceFormatted` (lance vencedor — ou current bid)
- `offerDetail.initialBidValue` (lance inicial — `minimum_bid_brl`)
- `offerDetail.reservedPrice` (preço de reserva; **não é avaliação**)
- `auction.{id, desc, beginDate, endDate, modalityDesc, judicialPracaDescription, auctioneer}`
- `product.{shortDesc, detailedDescription, photoCount, galleryJson[], productType.{id,description}, subCategory.{id,description,category.description}, location.{city, state, country, locationGeo:{lat,lon}}}`
- `totalBids`, `totalBidders`, `hasBids`, `winnerBid.currentWinnerLogin` (ofuscado)
- `seller.{name, city, company[].fantasyName}`

Pagination: `pageNumber=N&pageSize=30` (querystring). Total via
campo `total` na resposta. SPA também envia `pageSize=0` na
primeira chamada (apenas para count) — irrelevante para o spider.

URL do detalhe (SEO): `/oferta/{slug-do-shortDesc}-{offerId}`.
**`offerId` é o anchor canônico** — extrair via `re.search(r'-(\d+)$', path)`.
O slug muda se o `shortDesc` for editado; o `offerId` não.

## Listing encerrada

**Provider EXPÕE encerrados publicamente** — diferente de
`leilao_pro` e `cassiano`. O mesmo endpoint da listing ativa
aceita `searchType=closed`:

`GET offer-query.superbid.net/offers/?filter=stores.id:{storeId};product.productType.id:13&searchType=closed&orderBy=endDate:desc&pageNumber=N&pageSize=30`

- NP (16147): 5.389 closed offers (mas só 37 tagged como Imóveis,
  e esses são mis-tagged — productType=13 mas subCategory de
  carros/peças/relógios).
- Eckert (16063): **123 closed Imóveis legítimos**, com bids reais.
- JMF (16060): 121 closed Imóveis (a maioria sem lances).
- Barreto (16198): 13 closed Imóveis.
- Sala de Leilões (16178): 0 imóveis (categoria 124 = Eletrodomésticos
  + 18 = Tecnologia; tenant especializado).

Encerrados retornam:
- `offerStatus.statusCode=3` (= "wantToKnowThePrice", final)
  ou `closed=True` ou `sold=True`.
- `auction.allOffersOfThisAuctionIsClosed=True`.
- `winnerBid.currentWinner` (id) + `winnerBid.currentWinnerLogin`
  (string ofuscada `m*****la`) presentes se `totalBids>0`.

**Limitação**: `bids[]` (histórico individual com timestamp/valor/login)
**não é exposto a anônimos**. Apenas o agregado (`totalBids=165`,
`hasBids=true`, `winnerBid` ofuscado) é público. Endpoints
`api.s4bdigital.net/auction-event/offer/{id}/bids` retornam **401
Unauthorized**. Bid history requer JWT de usuário cadastrado/habilitado.

## Pilot lot escolhido

**URL**: `https://www.eckertleiloes.com.br/oferta/lote-urbano-n-5-localizado-na-rua-sao-jose-jardim-moretti-municipio-de-realeza-parana-area-de-50537-m-4429106`

- **offerId**: 4429106
- **auctionId**: 753981
- **storeId**: 16063 (Eckert Assessoria — Marciano Mauro Pagliarini)
- **Leilão pai**: "Município de Realeza/PR" (modalidade Leilão GOV,
  início 2025-11-04 10:00, encerramento 2025-12-04 10:00, praça única)
- **Lote**: 15 (lotNumber)
- **Título**: LOTE URBANO N° 5, LOCALIZADO NA RUA SÃO JOSÉ, JARDIM
  MORETTI, MUNICÍPIO DE REALEZA/PARANÁ — área 505,37 m²
- **subCategory**: Terrenos Urbanos (id 11811) → `property_type=terreno`
- **Endereço**: Realeza/PR (lat -25.768308, lon -53.531215)
- **Lance inicial**: R$ 60.000,00
- **Lance vencedor (preço final)**: R$ 151.500,00
- **`market_value_brl`**: null — provider não publica avaliação técnica;
  `reservedPrice` é igual ao `initialBidValue` (60.000) e representa
  preço-mínimo-de-reserva, não avaliação de bem.
- **totalBids**: 165 / **totalBidders**: 14 / **hasBids**: True
- **Vencedor**: `m*****la` (ofuscação server-side; já redigido pelo
  provider — mantido como está no `bidder_raw` se houvesse `bids[]`).
- **auction_status**: `arrematado`. Inferência:
  - `winnerBid.currentWinner=2413889` (id setado).
  - `auction.allOffersOfThisAuctionIsClosed=True`.
  - `endDate` no passado.
  - 165 bids, 14 bidders.
- **Imagens**: 7 fotos em `ms.sbwebservices.net/photos/{uuid}.jpg`.
  Filtro: incluir apenas host `ms.sbwebservices.net/photos/`
  (excluir logos em `static.s4bdigital.net/logos_empresas/`).
- **Documentos**: 0. Nenhum anchor PDF de edital/matrícula no detail.
  Matrícula nº 24.338 mencionada como **texto** na descrição.
  Edital pode existir no nível do auction (event) — não sondei a
  fundo (auth-required em algumas rotas).
- **bids[]**: vazio. Provider não expõe histórico individual a
  anônimos (`api.s4bdigital.net/auction-event/.../bids = 401`).

| Campo                      | Valor                                                   |
| -------------------------- | ------------------------------------------------------- |
| title                      | "LOTE 015 - LOTE URBANO N° 5, ..."                      |
| description                | descrição completa (HTML strip-pado)                    |
| property_type              | `terreno`                                               |
| address.raw_text           | "LOTE URBANO N° 5, QUADRA 419, RUA SÃO JOSÉ, ..."       |
| address.street_name        | "RUA SÃO JOSÉ"                                          |
| address.complement         | "LOTE URBANO N° 5, QUADRA 419"                          |
| address.district           | "JARDIM MORETTI"                                        |
| address.municipality_name  | "Realeza"                                               |
| address.uf                 | `PR`                                                    |
| address.cep                | null (não publicado)                                    |
| total_area_sqm             | "505.37"                                                |
| area_sqm                   | null (terreno sem benfeitoria)                          |
| market_value_brl           | null (provider não expõe avaliação técnica)             |
| rounds[1].minimum_bid_brl  | "60000"                                                 |
| rounds[1].scheduled_at     | 2025-12-04T11:07:58-03:00                               |
| rounds[1].status_raw       | "Praça Única - Arrematado por m\*\*\*\*\*la - R$ 151500" |
| auction_status             | `arrematado`                                            |
| bids[]                     | [] (não exposto a anônimos — 401)                       |
| images                     | 7 (ms.sbwebservices.net/photos/)                        |
| documents                  | 0 (não há anchor PDF público)                           |

## XHRs descobertas

Capturadas via Playwright `record_har_path` na home + listing + detail.
HARs em `pilot_xhr.har` (home) e `pilot_xhr_detail.har` (detail).

### Listagem
```
GET https://offer-query.superbid.net/offers/
    ?filter=stores.id:16063;product.productType.id:13
    &locale=pt_BR
    &orderBy=endDate:desc
    &pageNumber=1&pageSize=30
    &portalId=[2,15]
    &requestOrigin=store
    &searchType=closed
    &timeZoneId=America/Fortaleza
Auth: nenhum
Resposta: { total, start, limit, offers: [...], facetFields: [...] }
```

### Detalhe SEO
```
GET https://offer-query.superbid.net/seo/offers/
    ?filter=id:4429106;stores.id:16063
    &portalId=[2,15]
    &locale=pt_BR
    &timeZoneId=America/Fortaleza
    &requestOrigin=store
    &urlSeo={fullDetailURL}
Auth: nenhum
Resposta: idêntica a /offers/ filtrado por id, com seoBreadcrumb extra.
```

### Calendário do leilão
```
GET https://smart-schedule-api.superbid.net/event/{auctionId}/lot/{lotNumber}/event-schedules
Auth: nenhum
Resposta: { events: [{startDate, endDate, type, ...}] }
```

### Bid history (auth-only)
```
GET https://api.s4bdigital.net/auction-event/offer/{offerId}/bids
Auth: Bearer JWT (rejeita anônimo com 401)
```
Probes também 401: `/auction-event/offer/{id}`,
`/auction-event/auction/{auctionId}/bids`, `.../proposals`,
`.../history`. Não há rota pública alternativa para listar lances
(verificado em ~14 endpoints distintos).

### Métricas/heartbeat
```
POST https://api.s4bdigital.net/auction-event/visit/offer/{offerId}
Auth: nenhum (mas opcional). Body vazio.
```
Provider rastreia visualizações via essa rota — irrelevante para spider.

## Gotchas

1. **Multi-tenant via `storeId`**: 43 leiloeiros = 43 storeIds diferentes
   batendo no mesmo backend. O `style.config.json` por host fornece o
   `storeId` correto no boot. Não há autodescoberta — cache do mapping
   `host → storeId` deve viver em `data/intermediate/` no spider de
   produção. Mapping coletado neste recon: NP=16147, Eckert=16063,
   JMF=16060, Sala=16178, Barreto=16198.

2. **`portalId=[2,15]`**: literal — formato com colchetes faz parte da
   sintaxe de filtro do backend Superbid (Solr-like). Necessário em
   todas as queries; sem ele 400 Bad Request.

3. **Mis-tagging de NP Leilões**: NP retorna 37 lots com
   `productType.id=13` (Imóveis), mas o `subCategory.description` é
   `"Partes & Peças Carros"`/`"Motos"`/`"Relógios"`. Provavelmente
   migração de catalogação antiga. **Spider de produção em NP deve
   filtrar adicionalmente por `subCategory.category.description`
   contendo "Casas|Terrenos|Apartamentos|Salas|Galpões"** ou
   simplesmente skipar NP para imóveis. Eckert/JMF/Barreto não
   exibem esse problema.

4. **Bids 401**: histórico individual não é público. O agregado
   (`totalBids`, `winnerBid.currentWinnerLogin` ofuscado) é o único
   sinal anônimo. Se a Fase 2 quiser bids reais, precisará de
   credenciais — fora do escopo PLANOMESTRE (leitura passiva apenas).
   `bidder_raw` que viesse já estaria pseudonimizado pelo backend
   (formato `m*****la`).

5. **`reservedPrice` ≠ `market_value`**: o JSON tem
   `offerDetail.reservedPrice` mas no piloto e em outros lots
   amostrados ele bate com `initialBidValue` (preço-mínimo-de-reserva,
   não avaliação técnica). Avaliação independente **não é publicada**.
   `market_value_brl=null` é o correto. SOFT warning aceitável.

6. **Slug instável, offerId estável**: `/oferta/{slug}-{offerId}`. O
   slug é gerado de `product.shortDesc` na hora da publicação; se o
   leiloeiro editar o título, o slug muda. O `offerId` final (após
   o último `-`) é a chave canônica. Spider deve resolver
   `id={offerId}` via API e ignorar o slug.

7. **`.com.br` vs `superbid.net` como canonical**: alguns detail
   pages têm `<meta name="canonical">` apontando para
   `https://www.superbid.net/oferta/...`. Pode ser efeito do
   marketplace agregador — Superbid também publica os mesmos lots
   em seu portal próprio. Spider deve fixar o tenant
   (`eckertleiloes.com.br`) como autoridade do `source_lot_url`,
   não trocar para superbid.net.

8. **Time zone**: API serializa `endDate` como `"2025-12-04 11:07:58"`
   (sem TZ no string, mas timezone implícito é America/Sao_Paulo / UTC-3).
   `timeZoneId=America/Fortaleza` aparece na query string mas é só
   um override de display do cliente. **Sempre converter para `-03:00`
   tz-aware** antes de gravar `scheduled_at`/`timestamp`.

9. **Sem CEP**: `product.location` traz `city` e `state` mas não
   `cep`. Edital normalmente tem; spider de Fase 2 deve baixar
   edital (se exposto) ou inferir CEP via geocoding reverso a partir
   do `locationGeo` (lat/lon).

10. **PII**: `winnerBid.currentWinnerLogin` já vem **ofuscado pelo
    provider** (`m*****la`, `r******as`...). Nada a redigir do nosso
    lado para esse campo. Descrição do bem é institucional (sem CPF/PF).
    `seller.name="MUNICÍPIO DE REALEZA"` (PJ pública) — não redigir.
    Auctioneer = "KELLY CRISTINA MELLO" (PF leiloeira oficial) —
    agente público, não redigir conforme PLANOMESTRE §4.

11. **`hidePrices=true`**: alguns offers (incluindo o piloto) têm
    flag `hidePrices=true` quando o lote já encerrou — isso afeta
    apenas a UI ("clique para saber o preço"); o JSON ainda contém
    `priceFormatted` e `currentMaxBid` em claro. Não é PII —
    é UX para forçar engajamento.

## Decisões e limitações

- **`requires_playwright = False`** para o spider de produção. APIs
  JSON públicas cobrem 100% dos campos não-bid. Playwright só foi
  usado pra capturar HARs durante este recon.
- **`platform_hint = "s4b_digital"`**. Sinais canônicos:
  `static.s4bdigital.net` no `og:image`, `api.s4bdigital.net` em
  XHRs, `offer-query.superbid.net`+`event-query.superbid.net`+
  `siteconfigprod.superbid.net` como APIs de leitura, frontend SPA
  em React/MUI com bundle webpack `js/vendor.<hash>.js`.
- **`auctioneer_slug = "eckert-leiloes"`** no piloto. Decisão
  deliberada: `npleiloes` (representativo do _input.json) não tem
  imóveis legítimos no catálogo; o recon arquitetural cobre o
  **provider**, e o piloto cumpre o requisito do prompt
  ("leilão encerrado com lances") via Eckert.
- **`listing_active.url_pattern`** e **`listing_closed.url_pattern`**:
  parametrizados por `host` (entre `https://` e `/?...`) e
  `storeId` (na API JSON). O spider deve trocar ambos por tenant.
- **`bids[]` vazio no PilotItem**: documentado — não é falha do
  recon, é limitação real do provider. Skill `closed-auction-bids`
  §5: "Vários providers escondem o histórico após o leilão...
  Isso é legítimo — não invente." Aplicado aqui.
- **Documentos vazios**: edital/matrícula podem estar no nível do
  auction (event), não do offer; nessa instância (Município de
  Realeza/PR) não há PDF anchor exposto. Não é regra geral do
  provider (outros tenants podem expor) — é caso-a-caso.
- **Rate limit 1.5s**: respeitado em todos os fetches httpx
  (~25 requests, predominantemente JSON). HARs gerados via
  Playwright sem `slow_mo` mas com 1 visita-só (não há scraping
  iterativo no recon).
- **robots.txt**: permissivo; nenhum endpoint usado está em
  Disallow. `/cdn-cgi/*` ignorado (overhead Cloudflare). Spider
  produção fica dentro de `Allow: /`.
- **PII**: nada redigido. Login do vencedor já vem ofuscado
  server-side (`m*****la`). Descrição é texto institucional sem
  CPF/PF identificável. Seller é PJ pública (Município).
  Auctioneer é leiloeira oficial (agente público).
- **Sem download de binários**: imagens entram como URL apenas;
  PDFs, se existissem, idem.

## Status do validador

`validation.json::passed_hard = true` (1 tentativa). Fill rate:
18/25 = **72%**. SOFT warnings esperados:
- `market_value_brl ausente` — provider não expõe avaliação técnica.
- `address.cep ausente` — provider não retorna CEP no `product.location`.
- `nenhum documento listado (edital/matrícula)` — neste lote
  específico não há PDF anchor; outros lots do mesmo provider
  podem ter.

Esses 3 são **limitações documentadas do provider/lote**, não bugs
do recon. Promoção para Fase 2: avaliar se vale geocoding reverso
para CEP a partir de `locationGeo`, e tentar parse do edital
(se exposto a anônimos no nível auction).
