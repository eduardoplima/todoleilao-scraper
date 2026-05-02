# suporte_leiloes

Recon arquitetural do **provider `suporte_leiloes`** (Suporte Leilões / SL —
plataforma multi-tenant operada via `static.suporteleiloes.com.br`). 51
sites em `data/intermediate/site_analysis.csv` apontam para esta stack.

Tenant amostrado para o piloto: **`leilaobrasil.com.br`** (Irani Flores /
Dagmar Conceição de Souza Flores — `leilao-brasil` slug). Representa o
`_input.json` original (Irani Flores, MT). Spot-checks adicionais nos
3 maiores tenants do provider:
- `leilaobrasil.com.br` (Murilo + Dagmar — 2690 useful_links)
- `marcoantonioleiloeiro.com.br` (Marco Antônio — 716 links)
- `rodrigoleiloeiro.com.br` (Rodrigo Collyer — 716 links)

A escolha de `leilaobrasil.com.br` para o piloto é deliberada: é o site
com maior volume público (248 cards na home), o único onde encontrei
imóveis reais (não só veículos), e o representante explícito do
`_input.json` para o representative `Irani Flores`.

## Tech stack & rendering

`site_analysis.csv` (linhas 752, 6507, 6508) traz: `rendering=static`,
`tech_signals=server:cloudflare`, `static_useful_links=1345`,
`requires_js_for_listings=False`. Confirmado nos probes:

- **Server-side rendering** com layout Bootstrap-like + jQuery.
  Cards renderizados inline; status badges (status-1, status-3,
  status-96) emitidos no HTML inicial. SPA bundles (`/build/runtime.{hash}.js`,
  `/build/app.{hash}.js`, `/build/lote.{hash}.js`) só hidratam
  comportamentos client-side (carrossel PhotoSwipe, lightbox, share
  modais).
- **Plataforma `suporte_leiloes`** — sinais canônicos:
  - `var SL_USER = null;` em `<script>` inline (em todas as
    páginas). SL = Suporte Leilões.
  - CDN externa em `static.suporteleiloes.com.br/{tenant_slug}/...`
    onde `tenant_slug` é canônico por tenant (e.g.
    `leilaobrasilcombr` para leilao-brasil).
  - Auditório virtual em `arrematante.{tenant}.com.br` (subdomínio
    do próprio tenant), formato hash route
    `/#/auditorio/{leilao_id}` e `/#/cadastro`.
  - Bundles Webpack-style com hashes nos nomes (Symfony Encore
    likely, mas sem confirmação direta).
  - Dois padrões de path coexistem (legado + novo):
    - **Legado**: `/leilaobrasil/leiloes/lotes/imagens/{hash}.jpg`
    - **Novo**: `/leilaobrasilcombr/bens/{bem_id}/arquivos/sl-bem-{bem_id}-{ts1}-{ts2}.{ext}`
    - Documentos novos em `/leilaobrasilcombr/leiloes/{leilao_id}/documentos/sl-doc-{leilao_id}-{ts1}-{ts2}.{pdf|doc|docx}`
- **CDN/Hosting**: `server: cloudflare` (sem JS challenge no acesso
  normal; respondeu 200 em todos os probes com User-Agent custom).
- **Idioma/i18n**: pt-BR fixo. Datas em `DD/MM/YYYY HH:MM` (BRT,
  `-03:00`). Valores em `R$ N.NNN.NNN,NN`.
- **Tracking**: New Relic Browser RUM, Google Analytics G-L5TD82ZHST,
  Facebook Pixel.
- **`robots.txt`** (homogêneo entre tenants amostrados): contém
  apenas o **bloco de comentários** sobre Content-Signals do EU
  Digital Services Directive 2019/790. **Nenhuma regra
  `Disallow:` ou `Allow:`** explícita; nenhum
  `User-agent:` válido. Effetivamente *allow-all*. Nenhum
  content-signal é setado como `yes` ou `no` para search/ai-input/
  ai-train — neither grants nor restricts (cláusula c). Agregação
  para portal de leilões = use case search; respeitamos o espírito
  da licença.
- **Sitemap**: `/sitemap.xml` → 404, `/sitemap` → 404, `/sitemap_index.xml`
  → 404. Não há sitemap público.

**Conclusão**: `requires_playwright = False`. Toda a Fase 1 e Fase 2
podem rodar com `httpx` + `BeautifulSoup` puro.

## Listing ativa

URL canônica do tenant: **home `/`**. 248 cards renderizados na
resposta única, mistura de categorias (imóveis, veículos, máquinas,
equipamentos). Não há paginação visível (backend retorna *todos* os
leilões com data futura em uma única página).

Card selector: `article[class^='evento-index-']` — wrapper completo
de cada leilão. A classe contém o `leilao_id` 4-dígitos
(`evento-index-1325`, `evento-index-4308`). Estrutura por card:

- `strong.strong-cod` — texto: `Lote {N}` (5-dígitos sequencial =
  `bem_id` interno) ou `Lote {N} lotes` em multi-lote.
- `strong.strong-status` (com classe extra `status-1|3|96`) — badge
  visual.
- `h3` — título do leilão.
- `span.c-localizacao` — `'UF  - Cidade'` (com 2 espaços).
- `ul.cont-datas li` — 1+ praças. Cada `<li>` com:
  - `div.line-1 strong` — '1º Leilão' / '2º Leilão' / 'Leilão'
    (single-praça em venda direta extrajudicial).
  - `div.line-2 div.col-line` — Abertura, Fechamento (DD/MM/YYYY HH:MM).
  - `small.valInit` — 'Valor inicial: R$ N.NNN.NNN,NN' (= mínimo
    para participar; em judiciais = lance mínimo da praça).
- `a[href^='/eventos/leilao/{leilao_id}/']` — link canônico.

Status badges observados (na home):
- `status-1` → `Em breve` (218 cards) → `auction_status=ativo` (futuro).
- `status-3` → `Aberto para lances` (30 cards) → `auction_status=ativo`.
- `status-96` → `Cancelado` (2 cards) → `auction_status=cancelado`.

**Filtros server-side**: dropdowns `?tipo=leilao|vendaDireta|judicial|extrajudicial`
existem mas são apenas client-side. `?status=encerrado` (e variantes
`?status=2|4|5|6|7`, `?fase=encerrada`, `?evento=encerrado`,
`?tipo=realizado`) é silenciosamente ignorado pelo backend
(resposta byte-identical à home padrão; verificado por comparação de
`len(text)` e diff em probes).

## Listing encerrada

**`listing_closed: null` — provider NÃO expõe encerrados publicamente.**
Justificativa após probe sistemático:

1. **404 em rotas óbvias**: `/eventos/encerrados`, `/encerrados`,
   `/realizados`, `/leiloes-encerrados`, `/eventos/historico`,
   `/eventos/realizados` — todas 404.
2. **302 → / em rotas plurais**: `/leiloes/encerrados`,
   `/leiloes/realizados`, `/leiloes/historico` redirecionam para a
   home (sem filtro), apenas para "amaciar" UX errada.
3. **Sitemap ausente**: `/sitemap.xml` → 404. Sem index público de
   URLs históricas.
4. **Filtros server-side ignorados**: `?status=encerrado|2|4|5|6|7`,
   `?fase=encerrada`, `?evento=encerrado`, `?tipo=realizado` —
   todos retornam a home padrão, byte-identical. **Confirmado por
   diff de length** entre 6 variantes vs `/`.
5. **Status badge ausente**: nenhum card na home expõe
   `status-{N}` para `Encerrado`, `Arrematado`, `Vendido` ou
   `Sem licitante`. Vocabulário de status visíveis é fechado em
   `{1: Em breve, 3: Aberto para lances, 96: Cancelado}`.
6. **Lots passados acessíveis por id direto**, mas com **dados
   minados**:
   - **Sem strong-status badge** (detail page nunca renderiza status).
   - **Sem Avaliação** estruturada (`div.line-04` ausente em ~60% dos
     lots passados probed; lots ID 1000/5000/10000/15000/18000
     todos `aval=NONE`).
   - **Sem Valor inicial** (`small.valInit` só existe em cards da
     listagem, não no detail).
   - **Sem Histórico de Lances** real — todos os lots probed exibem
     "Nenhum lance até o momento" no `Histórico de Lances` e
     **3 propostas boilerplate** (TiagoFelipe R$ 1,00 em
     14/04/2025 18:43:11) idênticas em **TODOS** os lots da
     plataforma — dados de teste do site, não lances reais.
7. **Lots regenerados para datas futuras**: lot 138 ('Casa no
   Butantã') foi criado em 2018 (registro original) mas hoje
   (01/05/2026) aparece com 1ª praça em 04/05/2026 e 2ª em
   29/05/2026. **A plataforma sobrescreve** as datas do leilão a
   cada nova hasta — não há `auction_round` histórico imutável.
   Vide também o **typo `29/05/0226`** no HTML (lot 16883), que
   confirma falha de validação de input no backend.

**Caso paralelo**: `leilao_pro` (Fase 1 já recon) tem mesma limitação.
SOLEON, em contraste, expõe `/leiloes/encerrados` paginado com
`?page=N`. Aqui é o `listing_closed` que **não é exposto** —
documentação de limitação, não bug.

**Implicação para spider de produção**: única forma de acompanhar
ciclo de vida completo é **re-scrape diário** dos `leilao_id` ativos
antes da `Fechamento` da última praça. Lots que somem do índice
sem badge → `auction_status=desconhecido`. Resultado final
(arrematante, valor de fechamento) **não é publicado**. Para
enriquecer, monitor WebSocket no auditório virtual
(`arrematante.{tenant}.com.br/#/auditorio/{leilao_id}`) — escopo
Fase 3, requer auth.

## Pilot lot escolhido

URL: `https://leilaobrasil.com.br/eventos/leilao/casa-no-bairro-paineiras-do-morumbi-no-ibirapuera/lote/17523/casa-no-bairro-paineiras-do-morumbi-no-ibirapuera`

Leilão pai: `evento-index-1325` ("Casa no bairro Paineiras do Morumbi
no Ibirapuera", `leilao_id=1325`, single-lot). Modalidade ONLINE,
TJSP — judicial 2-praças. **`auction_status: ativo`** (1ª praça
abrindo hoje 01/05/2026 10h04 BRT, fechamento 04/05/2026; 2ª praça
04/05–29/05).

**Motivo da escolha**: dos lots ativos imóveis observados na home (22
hits após filtrar por `PROPERTY_CATEGORY_RE`), `lot 17523` foi o que
mais cumpriu campos HARD+SOFT do schema:
- Avaliação estruturada R$ 3.921.027,19 (atualizada).
- Endereço completo com CEP exposto: `Rua Joaquim Cândido de Azevedo
  Marques 1026, Vila Morumbi, São Paulo/SP — CEP 05688-021`.
- 2 praças (judicial Lei 9.514+CPC 879ss) com ambos `Valor inicial`
  expostos na listagem: R$ 3.964.434,97 (1ª) e R$ 1.982.217,49 (2ª =
  ~50% da avaliação atualizada).
- Descrição rica com matrícula, área (958 m² terreno + 318,89 m²
  edificado), cláusulas do edital.
- 1 imagem (placeholder ilustrativo, mas válida).
- 2 documentos (edital legacy `.doc` + edital novo `.pdf`).

| Campo                    | Valor (resumido)                                    |
|--------------------------|-----------------------------------------------------|
| auctioneer_slug          | `leilao-brasil`                                     |
| title                    | "Lote 7698 - Casa no bairro Paineiras do Morumbi no Ibirapuera" |
| property_type            | `casa`                                              |
| address.raw_text         | "Rua Joaquim Cândido de Azevedo Marques 1026, Vila Morumbi, São Paulo - SP. CEP 05688-021" |
| address.uf               | `SP`                                                |
| address.municipality_name| `São Paulo`                                         |
| address.cep              | `05688-021`                                         |
| area_sqm                 | "318.89" (área construída do prédio)               |
| total_area_sqm           | "958.00" (área do terreno)                         |
| market_value_brl         | "3921027.19" (Avaliação atualizada)                |
| rounds[1].minimum_bid    | "3964434.97" (1ª praça)                            |
| rounds[1].scheduled_at   | 2026-05-01T10:04:00-03:00                          |
| rounds[2].minimum_bid    | "1982217.49" (2ª praça, ~50%)                      |
| rounds[2].scheduled_at   | 2026-05-04T10:04:00-03:00                          |
| auction_status           | `ativo` (1ª praça abrindo hoje)                    |
| bids[]                   | **vazio** — não exposto pelo provider              |
| images                   | 1 (placeholder ilustrativo)                        |
| documents                | 2 (edital `.doc` legacy + edital `.pdf`)           |
| encumbrances_raw         | vazio                                               |

**`bids: []` deliberadamente vazio** — vide "Listing encerrada".

## XHRs descobertas

Não usei `xhr-first-recon` formal — site é estático e responde 200
em todos os endpoints HTTP padrão. Mas mapear infra para Fase 3:

- **Auditório virtual** em
  `arrematante.{tenant}.com.br/#/auditorio/{leilao_id}` (SPA hash
  router; provavelmente Vue/Angular). Lances ao vivo via WebSocket
  ou SSE — não inspecionado, requer auth (login obrigatório).
  Tópicos por leilão_id; canal compartilhado entre tenants é
  desconhecido.
- **POST `/login`** — Symfony route de auth. Fora de escopo
  (PLANOMESTRE: leitura apenas).
- **POST `/eventos/.../proposta`** — endpoint para envio de
  proposta judicial (Art. 895 CPC). Requer auth. Payload do
  histórico (`Histórico de Propostas` table) é populado server-side
  com 3 entradas hardcoded de teste (TiagoFelipe R$ 1,00) — não é
  query dinâmica.
- **`/cdn-cgi/l/email-protection`** — Cloudflare Email Decode
  (footer obfuscation, irrelevante para o item).

## Gotchas

1. **51 sites uniformes, mas 5 templates HTML**: tenants `leilao-brasil`
   (Murilo + Dagmar), `marcoantonioleiloeiro`, `rodrigoleiloeiro`,
   `jeleiloes` e demais 47 leiloeiros compartilham o mesmo template
   Symfony-like. Selectors no `selectors.yaml` são **portáveis**.
   O que muda entre tenants:
   - Subpath do CDN (`leilaobrasilcombr` vs `marcoantonioleiloeiro` etc.).
   - Identidade visual (logo no header, cores).
   - Conjunto de leilões/lotes (cada tenant é independente em DB).
   - URL do auditório (`arrematante.{tenant}.com.br`).
   - 2 padrões de path para imagens coexistem (legacy + novo).

2. **Lance Inicial só na listagem**: detail page **NÃO** renderiza
   `small.valInit`. Spider de produção precisa preservar o link
   listing→detail por `leilao_id` (4-dígitos) para correlacionar
   `minimum_bid_brl` com o lot. **Failure mode**: scrape direto do
   detail produz `minimum_bid_brl=null` e falha HARD do validador.

3. **Avaliação no detalhe pode aparecer 2× em texto**: descrição
   livre frequentemente cita "Avaliação histórica R$ X,XX" e
   "Avaliação atualizada R$ Y,YY". A estruturada em
   `div.line-04 ul.ul-01 li:has(strong:contains('Avaliação')) p` é a
   atualizada (corrigida por correção monetária). **Use a
   estruturada como `market_value_brl`, ignore as do texto livre**.
   Caso paralelo: lot 17523 mostra R$ 1.648.000 (2010) e R$ 3.921.027,19
   (atual) — só o estruturado é usado.

4. **Boilerplate de 3 propostas R$ 1,00 do TiagoFelipe** aparece em
   **TODOS** os lots na tabela `Histórico de Propostas`
   (14/04/2025 18:43:11). Confirmado em lots 100, 1000, 5000,
   16883, 17523, 23663, 23700, 23800, 23200. **Filtre fora**
   este record — é dado de teste do site, não proposta real.

5. **Typos no HTML**: lot 16883 mostra `Fechamento 29/05/0226 10:37`
   (4 dígitos do ano truncados). Spider deve usar regex permissivo
   (`\d{2,4}` no ano) e validar contra contexto (ano = ano corrente
   ou próximo) antes de quebrar.

6. **Lots regenerados**: `evento-index-138` (Casa Butantã, criado em
   2018) hoje aparece com 1ª praça em 2026. Backend reusa
   `leilao_id` em vez de criar novo evento. **Hash de identidade
   estável** = `(leilao_id, lot_id, scheduled_at)` — não só
   `leilao_id`. Bem (`bem_id`) é a unidade de longo prazo (ex.:
   matrícula 23.243 do prédio em Osasco vinculou-se a
   `leilao_id=4308` em 2026-03 e provavelmente já passou por
   outros eventos).

7. **Detail URL é canonicalizada por slug**: ao seguir
   `/eventos/leilao/{leilao_id}/{slug}/lote`, o servidor redireciona
   para `/eventos/leilao/{slug}/lote/{lot_id}/{slug}` (slug repetido
   na URL final). O `lot_id` (5-dígitos) só aparece no path final
   após redirect. Spider precisa seguir redirects.

8. **www vs apex e http vs https**: HTML do detalhe contém URLs
   apex (`https://leilaobrasil.com.br/...` sem www) em links de
   share (WhatsApp, Twitter, FB) e canonical-implicit. O server
   responde em ambos `www.` e apex via 200. Para `pilot_item.json`
   usei a forma APEX porque é a que aparece literalmente em
   `pilot_source.html` (validador HARD checa proveniência).
   `source_listing_url` mantém `www.` (forma usada para fetch).
   Spider de produção deve normalizar para uma das duas formas
   antes do dedup.

9. **Imagens placeholder são ubíquas**: tenant leilao-brasil em
   muitos imóveis serve apenas 1 imagem placeholder ilustrativo
   (`sl-bem-{bem_id}-{ts}.png` de ~10KB) com legenda "Imagem
   meramente ilustrativa". Não é falha do spider — é falta de
   conteúdo do operador. Marcado como SOFT (1 imagem ≥1 satisfaz
   o validador).

10. **PII no edital (PDFs)**: edital frequentemente cita CPF e nome
    completo do executado. **Não baixei nenhum PDF** (regra dura
    do recon). Em Fase 2, OCR + redação automática [CPF]/[PF]
    serão necessários antes de persistir o conteúdo do edital
    (PLANOMESTRE §4).

## Decisões e limitações

- **`requires_playwright = False`**: HTML estático totalmente
  suficiente. SPA bundles só hidratam comportamentos
  client-side (PhotoSwipe, share modais).
- **`platform_hint = "suporte_leiloes"`**: canônico, sem variantes
  observadas entre os 4 tenants amostrados.
- **`auctioneer_slug = "leilao-brasil"`** no piloto: slug derivado
  do nome do site (`Leilão Brasil`); o input.json original aponta
  Irani Flores como representativo do provider (51 sites).
  Recon arquitetural cobre o **provider**, não o leiloeiro
  individual — por isso vivemos em
  `specs/_providers/suporte_leiloes/`. O sub-tenant escolhido foi
  leilao-brasil pelo volume e pela representatividade do input.
- **`listing_closed = null`**: provider não publica encerrados
  com lances (justificado em "Listing encerrada"). O foco do
  prompt do usuário ("leilão encerrado com lances") **não é
  satisfeito** por este provider — é um achado arquitetural,
  não uma falha de recon.
- **`bids = []` no piloto**: provider não expõe histórico de
  lances publicamente. Lances reais ficam atrás de auth no
  auditório virtual. Boilerplate TiagoFelipe filtrado.
- **Pilot é lot ATIVO** (1ª praça em 01/05/2026), não encerrado:
  - HARD do validador exige `rounds[].minimum_bid_brl preenchido`
    — único conjunto de lots com `Valor inicial` exposto no
    HTML inicial são os **ativos** (status-1, status-3) na
    listagem. Lots passados perdem `valInit` e a maioria perde
    Avaliação também.
  - Validator passou HARD com fill-rate ≈88% (22/25 campos).
- **Rate limit 1.5s** mantido em todos os fetches (~25 requests no
  recon: home, agenda, mapa, robots.txt, 4 detalhes, 12 probes 404/302,
  6 probes filtros ?status=*, 4 probes URL pattern). Total ≈40s
  de delay efetivo.
- **Não baixei nenhum PDF nem imagem** (regra dura).
- **PII**: descrição do lot menciona "executado" mas sem nome PF
  identificado no texto exposto. CPF não aparece. Comitente é PJ
  pública (TJSP); leiloeiro (Irani Flores, JUCESP 792) é agente
  público. PII potencial reside nos PDFs (não baixados, não
  redigidos no piloto).

## Status do validador

`validation.json::passed_hard = true`, `hard_failures = []`,
`soft_warnings = []` (todos os SOFT passaram pela disponibilidade de
property_type, market_value_brl, address.uf, address.cep,
address.municipality_name + 1 imagem + 2 documentos).

Fill-rate: 22/25 campos (88%). Pendentes esperados:
- `address.complement` (não há complemento no endereço).
- `bids` (vazio — provider não expõe).
- `encumbrances_raw` (não estruturado no detalhe).
