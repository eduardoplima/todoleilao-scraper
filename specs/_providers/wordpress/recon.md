# wordpress

Recon arquitetural do **provider `wordpress`** — etiqueta de bucket
residual em `data/intermediate/site_analysis.csv` que reúne
leiloeiros cujo site usa **WordPress como CMS sem plataforma SaaS de
leilão dedicada** (em contraste com `soleon`, `leilao_pro`,
`leilotech`, `bomvalor` etc., que são plataformas reais
multi-tenant). 10 sites no bucket; o `_input.json` aponta como
representante **mvleiloes.com.br** (Maicon e Valéria Pontes Braga
Kahn — leiloeiros oficiais RJ).

Mas mvleiloes não tem plugin de leilão de fato — é showcase
estático. Para o objetivo do recon (**leilão encerrado com lances**),
o pilot foi extraído do tenant `fauthleiloes.com.br` (André Antônio
Fauth + Antônio Carlos Fauth, JUCERS — Caxias do Sul/RS), que usa
**WooCommerce + Ultimate WooCommerce Auction (UWA)** e tem histórico
de lances real exposto publicamente.

A conclusão central deste recon é arquitetural: **`wordpress` não
é uma plataforma; é uma família de stacks heterogêneos por baixo da
mesma assinatura `<meta generator="WordPress">`.** Spider único é
inviável; é necessária classificação por variant.

## Tech stack & rendering

`site_analysis.csv` (linha do mvleiloes, ID 6666) traz
`rendering=static`, `tech_stack=WordPress; jQuery; Bootstrap`,
`tech_signals=generator=WordPress 6.9.4 ... server:cloudflare`,
`requires_js_for_listings=False`, `static_useful_links=66`,
`dynamic_useful_links=66`. Confirmado em todos os 5 tenants
amostrados — todos retornam HTML 100% server-side via `httpx` puro.
**`requires_playwright = False`** universalmente para o bucket.

Survey rápido (apenas home + 1-3 páginas internas, 5 tenants):

| tenant            | generator     | woo | UWA | CPT/slug              | bids reais? |
| ----------------- | ------------- | --- | --- | --------------------- | ----------- |
| mvleiloes         | WordPress 6.9 | sim | NÃO | `/leilao_imoveis/`    | NÃO (showcase) |
| fauthleiloes      | WordPress 6.9 | sim | sim | `/leilao/{slug}/`     | **SIM** (escolhido) |
| luizcampolina     | WordPress 6.9 | sim | sim | `/produto/{slug}/`    | sim, mas amostra de 25 produtos só com "Leilão iniciado" sem licitantes |
| leiloesbonfadini  | WordPress 6.9 | NÃO | NÃO | (sem CPT)             | NÃO (Elementor) |
| fabioguimaraes    | WordPress 5.1 | NÃO | NÃO | `/portal/category/`   | NÃO (legacy blog) |

4 variants distintas:
1. **`woo-uwa`** (fauth, luizcampolina): WooCommerce + plugin
   Ultimate WooCommerce Auction. Bid history server-side em
   `<table class="auction-history-table">`. Body class
   `uwa_auction_status_{started,expired,future}`.
   Rota: `/leilao/{slug}/` (fauth) ou `/produto/{slug}/`
   (luizcampolina).
2. **`showcase-cpt`** (mvleiloes): custom post type
   `leilao_imoveis` registrado pelo tema/plugin proprietário, sem
   integração de leilão. Cards têm badge textual ("Em breve novas
   datas", "Leilão Judicial", "VENDA DIRETA CAEX") mas sem status
   estrutural para encerrado/arrematado. WooCommerce ativo para
   outras finalidades (loja?), não para leilão.
3. **`showcase-pages`** (bonfadini): WordPress + Elementor puro,
   sem WooCommerce, sem CPT de leilão. Lots viram páginas estáticas.
4. **`legacy-blog`** (fabioguimaraes): WordPress 5.1, posts
   tradicionais em `/portal/category/leiloes/`. Cada leilão é uma
   post normal.

**robots.txt** dos 5 tenants amostrados (homogêneo, default
WordPress + Yoast):
```
User-agent: *
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php
[Yoast block: User-agent: * Disallow: <vazio>]
Sitemap: <wp-sitemap.xml ou sitemap_index.xml>
```
Único tenant com regras adicionais: luizcampolina e fauth bloqueiam
`/wp-content/uploads/wc-logs/` e `/wp-content/uploads/woocommerce_*/`
(WooCommerce). Nenhum bloqueia páginas públicas. Rate limit 1.5s
mantido (~80 fetches no recon total).

## Listing ativa

**Não há padrão único.** Por variant:

- **`woo-uwa`**: tenants não expõem categoria pública só de imóveis
  ativos. Home + `/agenda-de-leiloes/` (fauth) ou `/categoria-produto/imoveis/`
  (mvleiloes/luizcampolina) costumam vir vazios ou com poucos lotes.
  A descoberta canônica é via **`product-sitemap.xml` (Yoast SEO)**
  — 73 produtos no fauth, 485 no luizcampolina. Iterar URLs +
  fetch detail + filtrar por body class
  `uwa_auction_status_started` ou `uwa_auction_status_future`.
- **`showcase-cpt`** (mvleiloes): home expõe os 18 lotes em cards
  estruturados; selector
  `a[href*='/leilao_imoveis/']`. Sitemap
  `wp-sitemap-posts-leilao_imoveis-1.xml` corrobora (mesmos 18).
  Pagination=none. Sem distinção UI ativo/encerrado.
- **`showcase-pages`** / **`legacy-blog`**: caso a caso; gener
  `category/{slug}/` ou `portal/category/leiloes/`. Spider por tenant
  individual.

## Listing encerrada

**Não existe rota pública dedicada em nenhum tenant amostrado.**
Probes em fauth (5 candidatos: `/leiloes-encerrados/`, `/encerrados/`,
`/categoria-produto/encerrados/`, `/leiloes-anteriores/`, `/shop/`):
todos 404. Mesmo no mvleiloes: `/encerrados/`, `/leiloes-encerrados/`,
`/category/encerrados/` retornam 404 do template padrão WordPress.

Fallback canônico para variant **`woo-uwa`**: usar
`product-sitemap.xml` como listing closed equivalent — Yoast lista
TODOS os produtos, e a discriminação ativo/encerrado vem via body
class no detail (`uwa_auction_status_expired`). Esta é a estratégia
adotada para o pilot:
`https://fauthleiloes.com.br/product-sitemap.xml` →
`https://fauthleiloes.com.br/leilao/apartamemto-florianopolis-sc/`.

Para variant **`showcase-cpt`** (mvleiloes) e demais: site
**não distingue** encerrado de ativo no front. Spider de produção
precisa de track de mudanças + heurística de data ("Em breve novas
datas" provavelmente = pré-leilão; ausência da badge = pode estar
ativo) — fora do escopo do recon Fase 1.

## Pilot lot escolhido

URL: **`https://fauthleiloes.com.br/leilao/apartamemto-florianopolis-sc/`**
(slug com typo "apartamemto" — preservado pelo provider).

Leilão: **APARTAMENTO 602 + Vaga 30 + Hobby-box 19 — Edifício
Residencial Montebello, Jardim Atlântico, Florianópolis/SC**.
Comitente: Construtora e Incorporadora Randon Aria (PJ pública —
mantém). Leilão Extrajudicial (alienação fiduciária Lei 9.514) com
1º Leilão em 10/02/2026 (deserto, R$613.000,00 = 100% avaliação) e
2º Leilão em 11/02/2026 às 16h00 (R$306.500,00 = 50% avaliação).

**Motivo da escolha**: o foco é leilão encerrado com lances. Probe
sistemático em 55 produtos imóvel-ish do fauth product-sitemap
revelou 15 com pelo menos 1 row em `auction-history-table`. Filtros:
não-test (sem "-copia"/"teste" no slug), maior bid count, residencial
(não comercial). Top 5 não-test:

| postID | bids | property_type      | url-slug                                    |
| ------ | ---- | ------------------ | ------------------------------------------- |
| 1082   | 11   | **apartamento**    | apartamemto-florianopolis-sc (escolhido)    |
| ?      | 20   | sala_comercial     | sala-comercial-no-702-edificio-life...      |
| ?      | 16   | sala_comercial     | sala-comercial-no-706-edificio-life...      |
| ?      | 15   | terreno            | terreno-urbano-bairro-sao-luiz-da-6a-legua  |
| ?      | 14   | sala_comercial     | sala-comercial-no-707-edificio-life...      |

Escolhi 1082 por ser **apartamento residencial** (property_type
canônico mais limpo) e ter **arrematante** identificável ("Leilão
expirou. O maior lance foi: c***...s" + lance final R$ 377.710,00
em 11/02/2026 15:59 — 1 minuto antes do encerramento). O 2º lugar
seria sala-comercial-702 com 20 bids, mas property_type=`comercial`.

Detalhes:
- **Lote único** do leilão (não há agrupador `/leilao/{id}/lotes`
  como no SOLEON; cada produto WooCommerce é seu próprio leilão).
- **Título**: `og:title` = "Apartamento Florianópolis/SC - Fauth
  Leiloeiro" → strip do sufixo do tenant. Final:
  "Apartamento Florianópolis/SC".
- **Tipo**: `apartamento` (descrição: "APARTAMENTO nº 602,
  localizado no 6º pavimento do edifício Residencial Montebello").
- **Endereço bruto**: "Rua João Evangelista da Costa, nº 1.145,
  Apartamento nº 602, 6º pavimento, Edifício Residencial Montebello,
  Jardim Atlântico, Subdistrito do Estreito, Florianópolis/SC".
  `cep=null` — descrição não publica CEP do imóvel (publica
  inscrições municipais 51.20.021.0346.027-608 e .053-510, mas não
  o CEP). Fase 2 derivar via geocoding.
- **AVALIAÇÃO** (1º Leilão): R$ 613.000,00.
- **Lance Inicial 2º Leilão**: R$ 306.500,00 (= 50% do 1º).
- **Despesas e encargos**: R$ 10.975,12 (não somados ao lance
  mínimo — separados na descrição; spider não soma).
- **2 rounds expostos** (variant woo-uwa para Lei 9.514 expõe
  ambos na descrição livre, ao contrário do SOLEON que expõe só a
  praça atual): round 1 (10/02/2026, deserto), round 2 (11/02/2026,
  arrematado).
- **Bids exposed**: **11 lances** capturados em
  `<table class="auction-history-table">` (table com tbody + thead
  estruturados — ideal para parser). Captura completa: 5 lances no
  dia 10 → 6 lances no dia 11. Triplicate em 15:59 (3 lances no
  último minuto). Arrematante: handle `c***...s` (63 caracteres,
  só 1ª e última letra visíveis — UWA já obfusca o handle; spider
  não precisa redigir, já vem redigido).
- **Imagens**: 4 fotos — todas screenshots em `.png` (não fotos do
  imóvel; provavelmente da área da matrícula ou do edital). Path
  `/wp-content/uploads/2026/01/`. Capturadas via
  `div.woocommerce-product-gallery__image > a[href]`.
- **Documentos**: 2 — `Edital de Leilão` (`.docx`!) +
  `Matrícula do Imóvel` (`.pdf`). `.docx` é raro mas existe nesta
  variant; `HttpUrl` aceita. Spider de produção pode probe-mime para
  classificar. **Não baixei** os arquivos (regra dura).
- **`auction_status: "arrematado"`** — body class
  `uwa_auction_status_expired` + texto "O maior lance foi: c***...s"
  + lance final acima do mínimo do 2º leilão → arrematado canônico.

| Campo                    | Valor (resumido)                                    |
| ------------------------ | --------------------------------------------------- |
| title                    | "Apartamento Florianópolis/SC"                      |
| description              | 2350 chars (descrição completa do edital, 2 rounds, dívida) |
| property_type            | `apartamento`                                       |
| address.raw_text         | "Rua João Evangelista da Costa, nº 1.145, Apto 602, 6º pav, Ed. Residencial Montebello, Jardim Atlântico, Subdistrito do Estreito, Florianópolis/SC" |
| address.uf               | `SC`                                                |
| address.municipality_name| `Florianópolis`                                     |
| address.district         | `Jardim Atlântico`                                  |
| address.cep              | null (descrição não publica)                        |
| area_sqm                 | "62.25" (área real privativa do apartamento)        |
| total_area_sqm           | null (apto + vaga 21,60m² + hobby-box 2,07m² não somados — itens separados não constituem 'total construída') |
| market_value_brl         | "613000.00" (1º Leilão = avaliação Lei 9.514)       |
| rounds[0]                | round 1, R$613.000, 10/02/2026 16:00 BRT (deserto)  |
| rounds[1]                | round 2, R$306.500, 11/02/2026 16:00 BRT (arrematado)|
| auction_status           | `arrematado`                                        |
| bids[]                   | 11 (chronological, oldest first; bidder_raw já obfuscado pelo plugin) |
| images                   | 4 (gallery WooCommerce)                             |
| documents                | 2 (edital `.docx` + matrícula `.pdf`)               |
| encumbrances_raw         | [] (descrição neste lote não traz cláusulas de ônus separadas; alienação fiduciária implica ônus 'imóvel sob alienação fiduciária Lei 9.514' mas não é citado explicitamente como cláusula isolada — Fase 2 inferir via comitente PJ + tipo extrajudicial) |

## XHRs descobertas

Não usei `xhr-first-recon` — toda variant é estática (HTML inicial
contém tudo). Variant `woo-uwa` tem endpoint AJAX para colocar bids
em tempo real
(`/wp-admin/admin-ajax.php?action=woo_ua_set_new_bid` + ações
`uwa_auction_*` aparentes em JS), mas isso é para usuário logado
durante leilão ativo — fora do escopo (e seria login-walled). Para
**dados históricos pós-encerramento**, o HTML é fonte completa.

Não há SignalR, WebSocket ou SSE público nos tenants amostrados.
A atualização real-time durante leilão ativo provavelmente usa
polling jQuery contra
`/wp-admin/admin-ajax.php?action=woo_ua_check_auction_status`.

## Gotchas

1. **`wordpress` é bucket residual, não plataforma**. Survey de 5
   tenants revelou 4 stacks distintos. Spider único é inviável;
   pipeline precisa classificar por variant antes de delegar para o
   parser. Sinais discriminantes confiáveis:
   - body class contém `woocommerce` → variant tem WooCommerce
   - body class contém `product-type-auction` ou texto
     `uwa_auction_status_` → variant `woo-uwa`
   - HTML inicial tem `/leilao_imoveis/` em hrefs → variant
     `showcase-cpt`
   - HTML inicial tem `category/leiloes/` ou `/portal/` → variant
     `legacy-blog` ou similar
   - Caso contrário: `showcase-pages` (Elementor + páginas
     estáticas) — investigação manual.

2. **`woo-uwa` obfusca bidder_raw automaticamente**. UWA mostra
   apenas 1ª e última letra do username (`c***...s` para um username
   começando com `c` e terminando com `s`). Não há PII nominal a
   redigir no `pilot_item.json` — vem pré-redigido pelo provider.
   Spider deve preservar a string como-está em `bidder_raw` (a
   estrutura do asterisco é informativa: 63 chars com só 2 letras
   visíveis sugere username muito longo, possivelmente email).

3. **Documento como `.docx`**. Fauth publica edital em formato
   Microsoft Word (`.docx`) na pasta `/wp-content/uploads/2026/01/`.
   `HttpUrl` aceita qualquer extensão. Spider de produção pode
   converter via `pandoc` ou `python-docx` se quiser indexar texto
   do edital; pipeline atual mantém URL referência.

4. **Slug com typo preservado**. `/leilao/apartamemto-florianopolis-sc/`
   (typo: "apartamemto" em vez de "apartamento"). É a URL canônica
   do tenant — preservar.

5. **2 rounds na mesma página (variant woo-uwa)**. Diferente do
   SOLEON (single-round na detail), variant `woo-uwa` em leilão
   extrajudicial Lei 9.514 expõe ambas as praças na descrição livre.
   Round 1 deserto (sem bids no dia 10) é inferível por:
   "Total de lances feitos: ... Leilão expirou ... O maior lance
   foi: c***...s" + último bid do dia 10 = R$ 306.500,00 = lance
   mínimo do round 2. Heurística: se primeiro bid >= lance mínimo
   round 2 e timestamps após data round 2 → round 1 deserto.

6. **`total_area_sqm` ambíguo em apartamento composto**. Pilot lot
   inclui apartamento (62,25 m²) + vaga (21,60 m²) + hobby-box
   (2,07 m²) — três entidades cadastrais distintas no mesmo lote.
   `area_sqm` vai com a unidade principal (apartamento). Não somei
   para `total_area_sqm` porque vaga e hobby-box são acessórios
   averbados separadamente, não "área construída total" do imóvel
   residencial.

7. **CDN não exclusiva**. Variant `woo-uwa` serve imagens direto de
   `wp-content/uploads/` no domínio do tenant (sem CDN externa
   dedicada como cloudfront/gocache do SOLEON). Cloudflare está na
   frente como reverse-proxy padrão, mas o path é o original do
   WordPress. Spider sem CDN-rewrite — usa as URLs como vêm.

8. **`product-sitemap.xml` (Yoast) é o único listing público
   completo**. Yoast SEO publica sitemap padrão em
   `<host>/wp-sitemap.xml` (WordPress 5.5+) ou
   `<host>/sitemap_index.xml` (Yoast com índice próprio). 100% dos
   5 tenants expõem. Usar isso como seed em vez de tentar paginação
   de `categoria-produto`/home.

9. **Nem todo "expired" tem bid**. ~80% dos produtos UWA expirados
   no fauth+luizcampolina amostrados tinham apenas
   `<tr class="start">Leilão iniciado</tr>` (sem licitantes) →
   `auction_status=encerrado` (não `arrematado`). Filtrar por
   presença de `<td class="bid_username">` antes de classificar.

10. **mvleiloes (representante do _input.json) é um caso degenerado**.
    18 lots em CPT custom, todos com badge "Em breve novas datas" /
    "Leilão Judicial" / "VENDA DIRETA CAEX" — não há campos de
    lance, leilão ou encerramento estruturados. É **showcase de
    leilões agendados**, com link externo presumido para o site real
    do leiloeiro/comitente. Spider para mvleiloes individualmente:
    extração baseada em descrição + título do post + manual; **sem
    cobertura de lances**. Não cabe no recon arquitetural — vira
    spec individual `specs/<slug>/` se priorizado em Fase 2.

## Decisões e limitações

- **`requires_playwright = False`**: HTML estático suficiente em
  todas as 4 variants observadas.
- **`platform_hint = "wordpress-woocommerce-uwa"`**: cobre apenas
  a variant escolhida para o pilot. Não é "platform_hint" no sentido
  estrito (não há plataforma multi-tenant) — é a string que o
  spider vai checar para entrar nessa rota de extração.
- **`auctioneer_slug = "wordpress"`** no piloto (não `fauthleiloes`):
  recon arquitetural do bucket. Vivemos em
  `specs/_providers/wordpress/`. Pilot efetivo em fauth porque é o
  tenant com bid history público + property_type residencial limpo.
- **`source_listing_url = product-sitemap.xml`**: o único listing
  público que enumera todos os lotes da variant woo-uwa. Para o
  bucket inteiro, esta URL é tenant-específica
  (`<host>/product-sitemap.xml` para WooCommerce/Yoast,
  `<host>/wp-sitemap-posts-leilao_imoveis-1.xml` para mvleiloes,
  etc.).
- **`listing_closed.url_pattern = product-sitemap.xml`** (mesma do
  active): UI pública não distingue. Filtro por body class
  `uwa_auction_status_expired` no detail.
- **`bids` capturado**: 11 lances chronological, com timestamp + valor
  + handle obfuscado pelo provider. Sem CPF nem nome PF a redigir.
- **PII redigida**: zero (provider já obfuscou bidder_raw). Sem
  CPF, sem nome PF nominal na descrição (comitente Construtora é
  PJ pública). `parser_notes` registra "redacted 0 — provider
  pre-obfuscates".
- **`address.cep = null`**: descrição não publica CEP do imóvel.
  Único SOFT warning. Fase 2 derivar via geocoding.
- **`total_area_sqm = null`** e **`encumbrances_raw = []`**:
  justificados acima (gotchas 6 e item da tabela).
- **Rate limit 1.5s** mantido em ~80 fetches (cross-tenant survey,
  amplas probes para confirmar heterogeneidade do bucket).
- **Não baixei nenhum binário** (regra dura). 4 imagens .png e
  2 documentos (.docx + .pdf) salvos como URL referência.
- **Cobertura do bucket**: o pilot cobre **2 dos 10 tenants**
  (fauth + luizcampolina via woo-uwa). Os 8 restantes precisam de
  classificação por variant (provavelmente 5-6 são showcase-cpt /
  showcase-pages / legacy-blog sem bid data exposta — caso de
  spider individual ou desistência por fonte ausente; equivalência
  ao caso `cassiano` em `pilot-extraction-protocol`).

## Status do validador

`validation.json::passed_hard = true`, **1 SOFT warning**
(`address.cep ausente` — limitação do provider/edital). 22 dos 25
campos do fill-rate preenchidos (88%); zerados:
- `total_area_sqm` (apartamento composto com 3 unidades cadastrais
  distintas — área principal 62,25m² em `area_sqm`; vaga 21,60m² e
  hobby-box 2,07m² não somáveis a total construída);
- `address.cep` (descrição não publica CEP do imóvel);
- `encumbrances_raw` (descrição não traz cláusulas de ônus
  estruturadas; alienação fiduciária Lei 9.514 implica ônus
  inerente mas não citado isolada — Fase 2 inferir via tipo +
  comitente).

Validador passou na **1ª tentativa**.
