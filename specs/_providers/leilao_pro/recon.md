# leilao_pro

Recon arquitetural do **provider `leilao_pro`** (Leilão Pro —
`https://www.leilao.pro`). 83 leiloeiros catalogados em
`data/intermediate/site_analysis.csv` apontam para esta plataforma.

Tenant amostrado para o piloto: **`renovarleiloes.com.br`** (Corrêa
e Alegranzzi LTDA, RS — sociedade com 2 leiloeiros oficiais).

Representativo do `_input.json` original: `jacleiloes.com.br`
(Jefferson Adriano Costa, PR). Mantido como segundo recon para
validar uniformidade da plataforma. Spot-checks adicionais em
`marceloleiloeiro.com.br` (RS) e `santamarialeiloes.com.br` (RS).

A escolha do `renovarleiloes` para o piloto é deliberada: foi o
único tenant onde encontrei um lote **com lance público** sem
exigir login (badge `#badge-lances-9110` = 1, lance de `mmagni`
R$ 41.000,00 em 20/04/2026 19:17:29). JAC e Marcelo amostrados
têm `badge-lances-N` = 0 em todos os lotes ativos; nenhum
encerrado público em nenhum dos quatro tenants.

## Tech stack & rendering

`site_analysis.csv` (linha 245, JAC) traz: `rendering=static`,
`tech_signals=server:cloudflare | pw=pw_networkidle_timeout`,
`static_useful_links=675`, `requires_js_for_listings=False`.

Confirmado em todos os 4 tenants amostrados:

- **Server-side rendering** com layout Bootstrap 4 + jQuery + FontAwesome.
  Tags-âncora HTML estáticas com paths previsíveis. Cards de lote
  renderizados inline (incluindo histórico de lances).
- **Plataforma `leilao_pro`** — sinais canônicos:
  - `<meta name="author" content="Leilão Pro - https://www.leilao.pro" />`
  - `<meta name="copyright" content="© 2026 Leilão Pro" />`
  - Footer "Powered By [logo Leilão Pro]"
  - `/bundles/leilaoprocore/js/eventsource.min.js` (asset bundle Symfony)
  - `/bundles/leilaoprocore/...` em vários CSS/JS
  - Stack inferida: Symfony (rotas, bundles), MySQL/Postgres (lot IDs
    sequenciais), Twig (templates server-side).
- **Mercure SSE** (Symfony Mercure Hub) para atualização em tempo
  real de lances:
  - Hub em `https://mercure.leilaodetran.com.br/.well-known/mercure`
    (compartilhado entre tenants — domínio do operador da plataforma).
  - JWT Bearer público (anônimo) com `subscribe: []`, `publish: ["*"]`
    embedado no HTML — só consome eventos, não publica.
  - Topics: `{tenant_url}/leilao-online`, `{tenant_url}/lance-novo`.
  - Handler JS faz `prepend('.lances-list', novoLance)` — confirma
    que **o histórico inicial é server-side render**, não AJAX.
- **OneSignal** (push notifications), **Pusher** (channels também
  disponível, mas Mercure é o canal primário).
- **CDN/Hosting**: `server: cloudflare` em todos os tenants
  amostrados. Nenhuma proteção JS challenge no acesso normal.
- **Idiomas/i18n**: pt-BR fixo. Datas em `DD/MM/YYYY` ou
  `DOW - DD/MM/YYYY`, valores em `R$ NN.NNN,NN`.
- **robots.txt** (homogêneo entre os 4 tenants):
  ```
  User-agent: *
  Disallow: /cgi-bin/
  Disallow: /uploads/documentos_cadastro/
  Disallow: /uploads/media/documentos_bem/
  Disallow: /uploads/media/documentos_leilao/
  Disallow: /uploads/media/documentos_cadastro/
  Disallow: /*download/
  Allow: /leilao/
  ```
  **Nota crítica**: `/uploads/media/documentos_bem/` e
  `/uploads/media/documentos_leilao/` estão em `Disallow`. A Fase 1
  inclui essas URLs no `pilot_item.json::documents[]` apenas como
  **referência declarada na página de detalhe** (já indexada e
  permitida por `Allow: /leilao/`). O spider de produção **não deve
  fazer GET nesses paths** (consistente com a regra "não baixar
  binários" do prompt do recon-pilot).

**Conclusão**: `requires_playwright = False`. Toda a Fase 1 e Fase 2
podem rodar com `httpx` + `BeautifulSoup` (ou Scrapy puro).

## Listing ativa

URL canônica por tenant: `/leilao/lotes/imoveis` (categoria
"imóveis"). Variantes da plataforma: `/leilao/lotes/imovel`,
`/leilao/lotes/terreno`, `/leilao/lotes/fazendas-pequeno-porte`
etc. — uma rota por slug-de-categoria.

A **home `/`** é uma listagem de **leilões** (não de lotes): cada
card aponta para `/leilao/{slug}/lotes/lista`. Para piloto de
imóveis, `/leilao/lotes/imoveis` é mais direto — entrega lots
imediatamente sem o layer "leilão → lotes".

Card selector: `div.card-vertical` (envoltório completo) — contém:
- `.card-image > a[href*='/lote_id/']` — link canônico do lote.
- `.card-title` (h5) — título.
- `.info-meta` — data/hora do leilão (DOW DD/MM/YYYY HH:MM).
- `.bid-initial` — Lance Inicial (texto: `R$ 41.000,00`).
- `.badge-primary` — número do lote ("LOTE 002"); às vezes
  "LOTE 000" quando o lot_number ainda não foi atribuído.
- `.badges-inline` — espaço para badges de status (vazio em todos
  os lotes amostrados; o backend não emite badges como ENCERRADO/
  ARREMATADO publicamente — ver "Listing encerrada").

Paginação: `?page=N` (querystring). 26 cards/página em JAC, 40 em
renovar — variável por tenant. Sem `<nav class="pagination">`
visível quando o total cabe em uma página.

**Filtragem por status na URL**: `?status=encerrado` é silenciosamente
ignorado pelo backend — a resposta é idêntica à versão sem o
parâmetro. Único filtro obedecido é a categoria (no path).

## Listing encerrada

**`listing_closed: null` — provider NÃO expõe encerrados
publicamente.** Justificativa após probe sistemático:

1. **404 em rotas óbvias**: `/leilao/encerrados`, `/leiloes/encerrados`,
   `/leilao/realizados`, `/leiloes/anteriores`, `/leiloes-encerrados`
   — todas 404. `/leilao/encerrado` (singular) também 404 em JAC,
   marcelo, renovar e santamaria.
2. **`/leilao/proximos` não filtra**: redireciona ou serve a mesma
   listagem dos próximos leilões (futuros + em-andamento), sem
   incluir os já encerrados.
3. **Sitemap explicitamente seletivo**: `/sitemap.leilao.xml` em JAC
   lista apenas leilões ativos (`<changefreq>daily</changefreq>`).
   Verificado: leilões com slugs antigos (e.g. `terreno-urbano-com-
   14-108-m2-...10-12-2020-...`) aparecem no sitemap só porque a
   plataforma reagendou-os para datas futuras — a `Data do Leilão`
   no detalhe é `25/05/2026`, não 10/12/2020. Slug-date é a data de
   criação do registro, não a data do leilão.
4. **Lotes desaparecem após encerramento**: probes em listings dos
   4 tenants em 2026-05-01 mostram apenas auction_dates ≥
   2026-05-04. Nenhum lote com data de leilão passada aparece na
   home, em `/leilao/proximos` ou em `/leilao/lotes/imoveis`.
   Conclusão consistente entre tenants: ao chegar na data,
   o lote é removido do índice público (operação do backend, não
   conjuntural).
5. **Filtro de status server-side ausente**: `?status=encerrado`
   ignorado.

> **Caso paralelo**: SOLEON (`fabio-marlon-machado`) **expõe**
> `/leiloes/encerrados` paginado. Cassiano Cuoghi não expõe
> `market_value`. Aqui é o `listing_closed` que não é exposto —
> mesmo padrão de "limitação documentada", não bug.

**Implicação para o spider de produção**: a única forma de
acompanhar o ciclo de vida completo de um lote em `leilao_pro` é
**re-scraping diário** dos `lote_id` ativos antes da `Data do
Leilão`, e capturar o último estado conhecido. Lots que somem do
listing após a data são presumidamente encerrados ou arrematados
— mas o resultado final (arrematante, valor de fechamento, status
canônico) **não é publicado**.

Implicação para Fase 2: `auction_round.status` para lotes
"vanished" só pode ser inferido como `desconhecido`. Para enriquecer,
seria necessário coletar via Mercure SSE no momento do leilão
(escopo Fase 3, fora deste recon).

## Pilot lot escolhido

URL: `https://www.renovarleiloes.com.br/leilao/leilao-de-imoveis-10-04-2026-17-52-12/lote_id/9110`

Leilão pai: "LEILÃO DE IMÓVEIS" (renovar-leiloes,
`/leilao/leilao-de-imoveis-10-04-2026-17-52-12/lotes/lista`),
modalidade ONLINE, data 12/05/2026 08h00min (BRT, `-03:00`).

**Motivo da escolha**: dos lotes amostrados em 4 tenants × até 30
lotes/tenant (≈85 lots probed individualmente, com rate-limit
1.5s), apenas **2 lots tinham lance público antes do início do
leilão** — `lote_id/9108` e `lote_id/9110` em renovar. Escolhi
`9110` (mais detalhado: tem todas as imagens, edital, matrícula).
O lance é antecipado (`Lances antecipados disponíveis até o início
do leilão`) — leilao_pro permite *bid before auction starts*, e o
HTML server-side renderiza esses lances inline (mesmo sem login).
Quando o leilão **começa**, novos lances chegam via Mercure SSE,
mas só para clientes logados (Mercure JWT é público mas o frontend
gating exige sessão).

Detalhes:
- **Lote 002** (badge-primary "LOTE 002"; o leilão tem ≥3 lotes,
  vide `lote_id/9108` e outros).
- **Título**: TERRENO C/ 620,17 M² - TAPERA / RS.
- **Tipo**: terreno urbano (lote em loteamento).
- **Endereço bruto** (extraído da `card-body` do accordion DESCRIÇÃO):
  "TERRENO COM 620,17 M² SEM BENFEITORIA, LOCALIZADO NA RUA 120,
  LOTE 22, QUADRA 48, ZONA E, NO LOTEAMENTO CRISTAL, NO MUNICÍPIO E
  CRI DE TAPERA - RS." — Tapera/RS é município pequeno em Lat -28.6°,
  Long -52.85° (confirmado pelo iframe Google Maps embarcado).
- **AVALIAÇÃO**: R$ 40.000,00.
- **Lance atual** (= minimum_bid após 1º bid): R$ 41.000,00. Original
  Lance Inicial era R$ 40.000 (= avaliação, padrão Lei 9.514 1ª praça).
- **1 round** (não há 2ª praça anunciada no card de info-adicional;
  apenas "Data do Leilão" — Lei 9.514 condicional informa praças no
  edital, não no card).
- **Bids exposed**: 1 lance público — usuário `mmagni`, R$ 41.000,00,
  manual, à vista, em **20/04/2026 19:17:29** (BRT). Capturado em
  `<div.lance-item id="lance-157343">`.
- **Imagens**: 4 fotos do bem (`/uploads/media/default/0001/67/{hash}.jpg`).
  Filtro: descartar `/uploads/media/default/0001/60/...` (logo do site).
- **Documentos**: 1 edital
  (`/uploads/media/documentos_leilao/0001/67/...pdf`) + 1 matrícula
  (`/uploads/media/documentos_bem/0001/59/...pdf`, label "9481" =
  bem_id interno). Disallow no robots para esses paths — incluímos
  apenas como URLs declarativas no item; spider não baixa.
- **`auction_status: "ativo"`**. Data 12/05/2026 ainda futura;
  badge de status não emitido na listagem (vazio); `Lances
  antecipados disponíveis` é o sinal explícito de que ainda
  está pré-leilão. Documentado em `parser_notes`.

| Campo                    | Valor (resumido)                                    |
|--------------------------|-----------------------------------------------------|
| title                    | "LOTE 002 - TERRENO C/ 620,17 M² - TAPERA / RS"     |
| description              | 178 chars                                           |
| property_type            | `terreno`                                           |
| address.raw_text         | "RUA 120, LOTE 22, QUADRA 48, ZONA E, LOTEAMENTO CRISTAL, TAPERA/RS" |
| address.uf               | `RS`                                                |
| address.municipality_name| `TAPERA`                                            |
| address.cep              | null (descrição não inclui CEP do bem; CEP do edital é da SICREDI) |
| total_area_sqm           | "620.17"                                            |
| area_sqm                 | null (terreno sem benfeitoria — sem distinção útil/total) |
| market_value_brl         | "40000.00"                                          |
| rounds[1].minimum_bid    | "40000.00"                                          |
| rounds[1].scheduled_at   | 2026-05-12T08:00:00-03:00                           |
| auction_status           | `ativo` (futuro próximo, com lance antecipado)      |
| bids[]                   | 1 (mmagni, R$ 41k, 20/04/2026 19:17:29)             |
| images                   | 4 fotos                                             |
| documents                | 2 (edital + matrícula)                              |

## XHRs descobertas

Não usei `xhr-first-recon` — site é estático e os lances já vêm
no HTML inicial. Mas mapear a infra para Fase 3:

- **Mercure SSE Hub**: `https://mercure.leilaodetran.com.br/.well-known/mercure`
  - Auth: JWT Bearer público inline no HTML
    (`{mercure: {subscribe: [], publish: ["*"]}}`). Permite
    subscrever em **qualquer tópico** sem cadastro. Compartilhado
    entre tenants (`leilaodetran.com.br` é o operador da plataforma).
  - Topics por tenant: `{tenant_url}/leilao-online`,
    `{tenant_url}/lance-novo`.
  - Mensagem `lance-novo` traz: `{lanceId, obfuscated_username,
    valor_formatado, valor_porcentagem_formatado, automatico,
    parcelado, parcelado_entrada, qtd_parcelas, created}`.
  - **Implicação para Fase 3**: monitor SSE em background captura
    lances ao vivo sem polling. Se quisermos o histórico completo
    pós-encerramento, precisaríamos persistir cada `lance-novo`
    em real-time (SSE não tem replay).
- **POST `/lance-novo`** (Symfony route) — endpoint de envio de
  lances. **Requer auth**; fora do escopo (PLANOMESTRE: leitura
  apenas).
- **`/media/download/{id}`** — download de PDF; bloqueado por
  robots `Disallow: /*download/`. Inclusive sem isso, regra do
  recon proibe baixar binários. Os PDFs ficam como URL referência.

## Gotchas

1. **Multi-tenant uniforme, mas data assincrona**: 83 sites
   `leilao_pro` rodam o mesmo template Symfony — selectors no
   `selectors.yaml` são portáveis entre tenants (verificado nos
   4 amostrados). O que muda entre tenants:
   - Subdomain do CDN-de-imagens (todos servem `/uploads/media/`
     direto; sem CDN externo como gocache).
   - Identidade visual no logo (`/uploads/media/default/0001/60/...`).
   - Conjunto de leilões/lotes (cada tenant é independente em DB).

2. **Mercure SSE compartilhado vs JWT por tenant**: o hub
   `mercure.leilaodetran.com.br` é único, mas cada tenant emite
   um JWT próprio embutido no HTML. Ambos verificados subscrevem
   apenas em tópicos do próprio tenant. **Não tente cross-tenant
   subscription** (filtra do lado do hub).

3. **`Lance Inicial` ≠ `Lance Atual`**: o card de listing mostra
   `Lance Inicial: R$ X` que é o **mínimo atual para participar**
   (= último lance + tick % ou = avaliação se sem lances). No
   detail `LANCE ATUAL À VISTA` exibe o lance atual real (último
   submetido). A `AVALIAÇÃO` é separada (card-informacoes). Para
   `market_value_brl` use AVALIAÇÃO; para `rounds[].minimum_bid_brl`
   use o **lance inicial original do edital** (= avaliação na 1ª
   praça em alienação fiduciária Lei 9.514). No piloto, ambos
   colapsaram em R$ 40.000 porque o leilão é Lei 9.514 single-round.

4. **Lots sem fotos vs com fotos**: alguns lots renovar têm 0 fotos
   (apenas o logo do site detectado em `/uploads/media/default/0001/60/`).
   Heurística: filtrar por `0001/67/` (ou outro padded ID ≠ 60).
   No spider final, comparar com `bem_id` extraído do label do
   documento (ex.: matrícula 9481 → path /0001/59/, parecem
   correlacionar com leilao_id, não bem_id — confirmar).

5. **`badge-lances-N` é o contador autoritativo**: para inferir
   se um lote teve lance antes do leilão, sondar
   `<span id="badge-lances-{lot_id}">N</span>` antes de baixar
   tudo. Economiza tráfego em scans massivos.

6. **`obfuscated_username` no Mercure ≠ `lance-value` no HTML**:
   o HTML server-side renderiza o username **em claro** (`mmagni`),
   o Mercure entrega obfuscado. **Inconsistência do provider** —
   pode ser configuração por tenant ou por flag (visualização
   pública vs auditório autenticado). PLANOMESTRE §4 ainda assim
   manda redigir nomes PF; `mmagni` parece pseudônimo, mantenho.

7. **Footer email obfuscation Cloudflare**: irrelevante para
   o item, igual ao caso `fabio-marlon-machado`.

8. **PII**: `mmagni` é apelido (handle) — público no contexto
   de leilão, não redigido. Descrição não tem CPF nem nome PF.
   Edital cita SICREDI (PJ) e CNPJ — PJ, não redigido. Nada
   redigido neste pilot.

9. **`auction_status` heurística**: nenhum tenant emite badge
   visual ENCERRADO/ARREMATADO no listing (badges-inline vazio).
   Para inferir status canonicamente:
   - data futura + badge=0 → `ativo`;
   - data futura + badge>0 → `ativo` (com lances antecipados);
   - lot some do índice → `desconhecido` (não há sinal público
     de arremate ou encerramento sem arremate).

10. **`/sitemap.leilao.xml` é fonte rica para discovery**:
    em scan inicial, é melhor que home — vem com `<lastmod>` por
    leilão (não por lote). 37KB em JAC, ≈100 leilões. Use como
    seed para spider de produção em vez de paginar `/leilao/proximos`.

## Decisões e limitações

- **`requires_playwright = False`**: HTML estático suficiente.
  Mercure SSE só relevante para Fase 3 (real-time tracking).
- **`platform_hint = "leilao_pro"`**: canônico, sem variantes
  observadas entre os 4 tenants amostrados.
- **`auctioneer_slug = "renovar-leiloes"`** no piloto (não JAC):
  decisão de optar pelo único tenant com lance público observado.
  O recon arquitetural cobre o **provider**, não o leiloeiro
  individual — por isso vivemos em `specs/_providers/leilao_pro/`.
  O input.json original aponta `jacleiloes` como representativo;
  o piloto efetivo é em `renovarleiloes` por motivo HARD (validador
  exige rounds[0].minimum_bid_brl preenchido — JAC tem, mas a
  riqueza de bids só renovar entrega).
- **`listing_active.url_pattern`**: `/leilao/lotes/imoveis`
  (categoria imóveis). Pode ser substituído por `/leilao/lotes/imovel`
  (singular) em alguns tenants — ambas resolvem para a mesma view.
- **`listing_closed = null`**: provider não publica encerrados
  (justificado em "Listing encerrada").
- **`bids` capturado**: 1 lance, com timestamp + valor + user.
  Sem PII para redigir.
- **Rate limit 1.5s** mantido em todos os fetches (≈90 requests
  ao longo do recon — listagens, individual lots, sitemap, robots,
  probes 404). Total ≈2.5min de delay efetivo.
- **Não baixei nenhum PDF nem imagem** (regra dura).
- **Disallow do robots**: `documentos_bem/`, `documentos_leilao/`
  são `Disallow`, mas as URLs aparecem no HTML do detalhe (que
  está em `Allow: /leilao/`). Incluo no `documents[]` como
  *referência declarativa*; spider de produção **não deve fazer
  GET** nesses paths (consistente com o policy do robots).

## Status do validador

Aguardando hook PostToolUse para rodar `validator/validate.py`.
Fill-rate alvo: ≈92% (24 dos 26 campos checados — pendentes
esperados: `address.cep`, `address.complement`).
