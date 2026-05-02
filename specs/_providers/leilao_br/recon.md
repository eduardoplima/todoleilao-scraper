# leilao_br

## Resumo arquitetural

`leilao.br` é, na prática, um **domínio guarda-chuva multi-stack**, não
um único provider. Os 18 sites listados em `_input.json:n_sites_in_provider`
hospedam **pelo menos duas plataformas distintas** sob o mesmo TLD:

1. **e-leiloes Nuxt SSR** — usado por `confiancaleiloes.leilao.br`
   (representante) e `e-leiloeiro.leilao.br`. **Este blueprint cobre
   este stack.**
2. **leilao_pro/Laravel** — usado por `donizetteleiloes.leilao.br`,
   `ferronato.leilao.br`, `nsleiloes.leilao.br` (`/build/*.css`,
   `<meta name="csrf-token">`, rotas `/leilao/encerrados`,
   `/arrematante/cadastro`). Stack diferente; **precisará de blueprint
   próprio**.

Single-tenant por leiloeiro, multi-stack no domínio. O `select_arch_batch.py`
agrupou tudo em um provider só por causa do TLD `.leilao.br` — esse
clustering precisa ser refinado em pré-processamento (heurística:
presença de `__NUXT_DATA__` vs `csrf-token`).

## Tech stack & rendering

- **Framework**: Nuxt 3 (Vue) com SSR.
- **Rendering**: `hybrid` no `site_analysis.csv` — confirmado. O HTML
  inicial já contém `<script id="__NUXT_DATA__" type="application/json">`
  com todos os dados de listagem/detalhe. Hidratação no cliente apenas
  para interatividade.
- **Domínio de assets/API**: `static.e-leiloes.com.br` (CDN com fotos,
  PDFs); `arrematante.e-leiloes.com.br` (auditório de lances, exige
  login). `www2.confiancaleiloes.com.br` (legado PHP) ainda aparece em
  alguns leilões antigos.
- **CDN**: Cloudflare (`server: cloudflare`, headers `cf-cache-status`).
- **Robots**: `User-agent: *  Allow: /` — sem restrições. Sitemap declarado
  aponta para `e-leiloes.com.br/sitemap.xml`.
- **`requires_playwright`: false.** Tudo vem do SSR.

## URL patterns

- **Home**: `https://www.confiancaleiloes.leilao.br/`
- **Listing por categoria**: `/leilao/{categoria}` (`imoveis`,
  `automoveis`, `maquinas-e-equipamentos-industriais`, com subcategorias
  `/leilao/imoveis/apartamentos`, `/leilao/imoveis/casa`, etc.).
  Paginação `?page=N`.
- **Listing por edital (leilão)**: `/editais?aba={abertos|encerrados|futuros|tudo}`.
- **Detalhe do leilão**: `/eventos/leilao/{leilao_id}/{slug}`. SSR retorna
  todos os lotes do leilão dentro de `__NUXT_DATA__`. Anchors para os
  lotes individuais aparecem só em links de compartilhamento (WhatsApp,
  Twitter, Facebook) — não em cards próprios.
- **Detalhe do lote**: `/lotes/{lot_id}/{slug}`. Página por lote
  individual. `__NUXT_DATA__` traz objeto completo: `lote`, `lote.bem`
  (imóvel ou veículo), `lote.leilao`, imagens, documentos, datas de
  praças, lances.
- **Venda direta**: `/eventos/venda-direta/{id}/{slug}` (variante sem
  praça/timer). Mesmo `__NUXT_DATA__`.

## Bid history

- **Onde**: `data.lote.lances` (lista) dentro de `__NUXT_DATA__`.
- **Selector/endpoint**: `script#__NUXT_DATA__::text` → JSON parse →
  resolver índice apontado por `lote.lances` e iterar.
- **Qualidade**: **n/a — não exposto publicamente**. Para todos os
  lotes encerrados que inspecionei (`23383`, `23381`, `23482`, `23480`,
  `23483`), `lote.lances` veio `[]` no SSR mesmo após o leilão. O campo
  `totalLances` aparece como referência interna (`6` → ponteiro pro
  índice 6 do array Nuxt, que é `None`); `valorArremate` também `None`
  e `arremate: None`. Histórico real fica atrás de auth em
  `arrematante.e-leiloes.com.br`. **Apenas valores das praças e
  status final** (`_status_variant: encerrado|arrematado`) ficam
  públicos.
- O `auction_status: arrematado` vs `encerrado` é distinguível no
  payload: `valorArremate != None` e/ou `arremate != None` indica
  arrematação. No piloto, `valorArremate=None` → `encerrado`.

## Pilot lot escolhido

- **Slug/URL**: `https://www.confiancaleiloes.leilao.br/lotes/23383/casa-residencial-com-terreno-de-200m2`
- **Status**: `encerrado` (event 1727 — 1ª Vara Cível de Santa Rita do
  Passa Quatro/SP, `_status_variant: encerrado`, `_status_label: Encerrado`).
- **Motivo**: imóvel residencial puro (Casa, terreno 200m², edificação
  126,21m²), endereço completo (Rua das Rosas, 50, Jardim Nova Santa
  Rita, Santa Rita do Passa Quatro/SP, CEP 13670-000), 13 fotos,
  matrícula em PDF, edital, jornal — fill rate alto. Único lote do
  leilão (`totalLotes=1`), 2 praças com `minimum_bid_brl` distintos
  (R$ 280.000 → R$ 168.000 com 60% de desconto). Sem PII na descrição
  (executados aparecem em `bem.processoExecutado`, fora do `PilotItem`).

## Portabilidade

Testes em sites de `_input.json:sites_in_provider`:

| Site                              | Stack                      | `__NUXT_DATA__` | Estratégia portável? |
|-----------------------------------|----------------------------|-----------------|----------------------|
| confiancaleiloes.leilao.br (rep)  | e-leiloes Nuxt SSR         | sim             | sim (base)           |
| e-leiloeiro.leilao.br             | e-leiloes Nuxt SSR         | sim             | **sim — idêntico**   |
| donizetteleiloes.leilao.br        | leilao_pro/Laravel         | não             | não — outro stack    |
| ferronato.leilao.br               | leilao_pro/Laravel         | não             | não — outro stack    |
| nsleiloes.leilao.br               | leilao_pro/Laravel         | não             | não — outro stack    |

Conclusão: este blueprint **só serve** os 2 sites Nuxt. Os demais
13/18 sites do "provider" precisam de outro recon (provavelmente
agrupados num blueprint `leilao_pro`). Recomendo refinar `select_arch_batch.py`
para clusterizar por **template HTML** (ex.: hash do CSS bundle ou
presença de `__NUXT_DATA__`/`csrf-token`), não por TLD.

## Gotchas

1. **`__NUXT_DATA__` é flat array com refs inteiras**. O JSON parse
   normal produz uma lista; valores semânticos são resolvidos por
   índice (`data[obj.descricao]`). O parser precisa fazer essa indireção
   recursivamente. Pense: estado serializado tipo Vuex/Pinia.
2. **Campo `timezone` dentro de cada `dataX`**: vem como
   `'America/Fortaleza'` (UTC-3) mesmo para imóvel em SP — tratar como
   metadado e usar **offset fixo `-03:00`** ao serializar (Brasil sem
   DST desde 2019). O timestamp em si é wall-clock local correto.
3. **`bem.cep`** vem **sem máscara** (`13670000`). Pydantic aceita ambos;
   normalizei manualmente para `13670-000` no piloto.
4. **`bem.tipoPai` é a categoria-mãe** (`Imóveis`, `Veículos`,
   `Máquinas`); use ela como filtro principal antes de mapear `tipoPai →
   property_type`. `bem.tipo` é o subtipo (`Casa`, `Apartamento`,
   `Terreno`, etc.).
5. **HTML markup do `siteDescricao`**: vem com `<br>` literal. Strip
   antes de gravar `description` ou normalizar para `\n`.
6. **`processoExequente`/`processoExecutado` em `bem`** trazem nomes
   PF — **não copiar para `description`/`raw_text`**. Eles ficam fora
   do `PilotItem` por design (não há campo). Em Fase 2, usar
   `core.party_identity` com hash + TTL.
7. **Listings de categoria** (`/leilao/imoveis`) **não trazem cards
   diretos para lotes** — só links para o evento (`/eventos/leilao/{id}/{slug}`).
   O spider precisa fazer 2 hops: home → evento → lote.
8. **Arrematante real**: `arrematante.e-leiloes.com.br` exige cadastro
   + 2FA (`TwoFactorRequirementModal` no Nuxt). Sem auth, não há
   histórico de lances público. Este é um **limite do provider**, não
   bug do recon.

## Decisões e limitações

- **`bids: []`** no piloto, com `parser_notes` explicando. SOFT por
  design.
- **Spider final usa httpx + JSON, não Playwright** — `__NUXT_DATA__`
  está no SSR. Reduz custo ~10× vs Chromium.
- **Blueprint só cobre o sub-stack Nuxt**. Os outros sites do "provider
  leilao_br" (Laravel/leilao_pro) precisam de outro recon. Reportar
  ao orquestrador.
- **`source_listing_url`** apontou para `/editais?aba=encerrados` (a
  porta de entrada para encerrados), não para o evento específico —
  isso bate melhor com o conceito de "listagem de origem" do schema.
- **Address parsing** feito manualmente a partir do `bem.endereco/numero/...`
  — em Fase 2, normalização IBGE entra (`municipality_code`).
