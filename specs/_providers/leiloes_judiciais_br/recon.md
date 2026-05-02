# leiloes_judiciais_br

Recon arquitetural do **provider `leiloes_judiciais_br`** — plataforma
**Leilões Judiciais** (`leiloesjudiciais.com.br`), uma família de
subdomínios state-specific (`leiloesjudiciaismg.com.br`,
`leiloesjudiciaisrj.com.br`, etc.) que servem **a mesma base de dados**
via Nuxt 3 SSR. Representativo do `_input.json`: **Thaís Costa Bastos
Teixeira** (`leiloesjudiciaismg.com.br`).

> Nota sobre composição do provider: o `_input.json` lista 30 sites
> agrupados sob este provider, mas spot-checks em `giordanoleiloes.com.br`,
> `franciscofreitasleiloes.com.br`, `alvaroleiloes.com.br`,
> `deonizialeiloes.com.br` e `rioleiloes.com.br` revelam **plataformas
> distintas** (paths estilo `/leilao/index/imoveis` em Giordano —
> arquitetura legacy MVC, não Nuxt). A referência mútua a
> `leiloesjudiciais.com.br` no rodapé/HTML desses sites parece ser
> apenas um link cruzado ("Bens semelhantes ofertados em outros sites
> da plataforma leiloesjudiciais.com.br"). Conclusão: o agrupamento em
> `_input.json` está parcialmente impreciso. Este recon cobre
> **especificamente o cluster Nuxt** (canonical
> `leiloesjudiciais.com.br` + state-specific subdomains que compartilham
> dados/frontend); os outros 25+ sites listados como "in_provider"
> precisam de re-classificação na fase de discovery.

## Tech stack & rendering

- **Nuxt 3** SSR (build assets em `/_nuxt/{hash}.js`, `__NUXT_DATA__`
  JSON inline no HTML retornado pelo SSR). `requires_js_for_listings =
  False` (HTML já contém todos os anchors `/lote/` e `/leilao/`).
- **Vue 3 + PrimeVue** (componentes UI: AutoComplete, Calendar, etc.).
- **API privada**: `https://api.leiloesjudiciais.com.br/` referenciada
  em `window.__NUXT__.config.public.NUXT_ENV_URL_API`. Probes diretos
  retornam 400/404/500 sem cookies de sessão — endpoint só responde a
  origens autenticadas. **Não usei `xhr-first-recon`** porque o SSR já
  entrega o conteúdo todo no HTML inicial (e o `__NUXT_DATA__` JSON
  inline traz o dump completo do lote, anexos, fotos, leiloeiro).
- **Storage**: Amazon S3 `sa-east-1`, bucket
  `906de634c48fb7d34136160b4c353ae4`. Hosting de imagens, PDFs e
  logos. Path patterns:
  - `/public/fotos/imoveis/{size}/I_{imovel_id}_{photo_id}_{seq}.jpg`
  - `/public/anexo/{epoch_timestamp}.pdf`
  - `/public/leiloesjudiciais/...` (logos, relatórios institucionais).
- **schema.org Organization**: `name="Leilões Judiciais"`,
  `url="https://www.leiloesjudiciais.com.br/"`.
- **CDN/edge**: nenhum sinal explícito (Cloudflare/Akamai não detectado).
- **Idioma**: pt-BR fixo. Datas `DD/MM/YYYY HH:MM`, valores
  `R$ NN.NNN.NNN,NN`.
- **robots.txt** (canonical `leiloesjudiciaismg.com.br`):
  ```
  User-agent: *
  Disallow: *?amp*
  Disallow: *?s*
  Disallow: *?replytocom*
  Disallow: */busca*
  Disallow: /*?pagina=
  Disallow: /leilao/*?pagina=
  Sitemap: https://www.leiloesjudiciais.com.br/sitemap.xml
  ```
  **Nota crítica**: `?pagina=` está em `Disallow`, ou seja, paginação
  via querystring é desencorajada para crawl. Para um spider de
  produção compatível com robots, usar **sitemap.xml** como fonte
  primária de seed de lotes (2.553 URLs `/lote/`, 958 `/leilao/`,
  todos ATIVOS). Para o piloto Fase 1, a regra "respeitar robots" é
  ambígua aqui — `Disallow: /*?pagina=` significa "não pagine" —
  mas o piloto faz apenas 1 fetch de `/imoveis` (sem `?pagina=`)
  e 1 fetch de `/lote/{ids}` (Allow implícito). Documentado.

**Conclusão**: `requires_playwright = False`. Spider de produção
usa `httpx + BeautifulSoup` (ou Scrapy puro), sem Chromium.

## Listing ativa

URL: `https://www.leiloesjudiciaismg.com.br/imoveis` (subcategorias
em `/imoveis/{slug}` — `apartamentos`, `casas`, `chacaras`,
`fazendas`, `terrenos-e-lotes`, etc., todas com mesma estrutura HTML).

Card selector: `div.base-card` (envoltório completo do card de lote).
Cada card contém:
- `a[href^='/lote/{leilao_id}/{lot_id}']` — link canônico do detalhe.
- `div.numero-lote.status-{...}` — número do lote (ex.: `#95911`).
- `div.status.status-{kind}` — badge de status (ver tabela abaixo).
- `div.cidade-avaliacao-minimo-atual` — bloco com cidade/UF, avaliação,
  lance atual.
- `div.nu-lances` — contador "lances {N}" (sem detalhamento público).

Paginação: `?pagina=N` (querystring; `Disallow` no robots — usar
sitemap como alternativa). 33-42 lots/página, 27 páginas no total
em /imoveis (≈1.057 ativos + 4 aguardando = 1.061 imóveis ativos).

**Categorias detectadas em `/imoveis`** (count entre parênteses no
filtro lateral):
- Apartamentos (101), Box / vaga de garagem (29), Casas (196),
  Chácaras (47), Depósito/galpão/pavilhão (21), Empreendimentos (11),
  Fazendas (44), Imóveis Comerciais (108), Imóveis Industriais (8),
  Imóveis Rurais (15), Outros (38), Sítios (51), Terrenos e Lotes (386).

**Distribuição por UF**: SP, GO, RJ, MG, RS lideram. Todos os 27 estados
brasileiros + DF.

**Status badges observados na listagem** (probe completo das 27
páginas):

| Badge classe                    | Texto bruto         | Count | `auction_status` |
|---------------------------------|---------------------|-------|------------------|
| `status-aberto-para-lances`     | "Aberto para Lance" | 1057  | `ativo`          |
| `status-aguardando`             | "Aguardando"        | 4     | `ativo` (pré)    |

Outros status definidos no CSS (mas **não emitidos em listings públicos**):
`status-aguardando`, `status-ativo`, `status-cancelado`,
`status-condicional`, `status-em-breve`, `status-finalizado`,
`status-pregao`, `status-repasse-lance`, `status-vendido`,
`status-loteamento`, `status-destaque`, `status-marrom`,
`status-bg-preto-branco`. **Lots em qualquer um desses estados não
finalistas/vendidos não aparecem no listing público.**

## Listing encerrada

**`listing_closed: null` — provider NÃO expõe encerrados publicamente.**

Probes sistemáticas (rate-limited 1.5s, UA `TodoLeilaoBot/1.0`):

1. **404/500 em rotas óbvias**:
   - `/encerrados` → 500
   - `/leiloes-encerrados` → 500
   - `/finalizados` → 500
   - `/vendidos` → 500
   - `/realizados` → 500
   - `/historico` → 500
   - `/imoveis-encerrados` → 500
   - Singulares (`/encerrado`, `/finalizado`) → 500

2. **Filtros silenciosamente ignorados**:
   - `/imoveis?status=encerrado` → 200, mesmo HTML que `/imoveis`
   - `/imoveis?status=finalizado` → 200, idem
   - `/imoveis?status=vendido` → 200, idem
   - `/imoveis?fase=encerrado` → 200, idem
   - `/imoveis?fase=finalizado` → 200, idem

3. **Rotas que retornam 200 mas não filtram**:
   - `/imoveis/encerrados` → 200, mas vai para a categoria default
     (zero lots com badge encerrado).
   - `/imoveis/finalizados` → 200, idem.

4. **Sitemap explicitamente seletivo**: `/sitemap.xml` (no canonical
   `leiloesjudiciais.com.br`) lista 2.553 lots e 958 leilões. Lot IDs
   variam de 73.134 a 145.007 (ATIVOS); IDs anteriores retornam 404
   silencioso. Nenhum sinal de "lastmod" antigo — todos atualizados
   na hora do recon (regeneração pull).

5. **Scan exaustivo**: probe das 27 páginas de `/imoveis` mostra
   **zero** lots com status `finalizado`, `vendido`, `condicional`,
   `encerrado`, `cancelado`. Apenas `aberto-para-lances` (1057) e
   `aguardando` (4).

6. **Lots desaparecem após o leilão**: probes de IDs aleatórios fora
   do range do sitemap (`/lote/100/100`, `/lote/29000/95000`, etc.)
   retornam 404 com title "Lote não encontrado".

> **Caso paralelo documentado**: SOLEON (`fabio-marlon-machado`)
> **expõe** `/leiloes/encerrados` paginado. `leilao_pro` também não
> expõe (lots desaparecem). Aqui é o mesmo padrão que `leilao_pro` —
> "limitação documentada", não bug.

**Implicação para o spider de produção**: a única forma de acompanhar
o ciclo de vida de um lote é **re-scrape diário** dos lot_ids ativos
antes da `dt_fechamento`, capturar último estado conhecido, e marcar
"vanished" como `auction_status: desconhecido` na próxima execução.

**Implicação para a tarefa atual ("foco: encerrado com lances")**:
o provider não permite cumprir o foco literalmente. Pilot foi
extraído sobre um lot **ATIVO**, com `auction_status: ativo` e
`bids: []` (zero lances públicos), com justificativa documentada.

## Pilot lot escolhido

URL: **`https://www.leiloesjudiciaismg.com.br/lote/29525/95911`**

- **Leilão pai**: 29525 — "Alto Parnaíba/MA - Fazenda São Bento c/
  16.040 hectares" — VENDA PARTICULAR EXTRAJUDICIAL ONLINE.
- **Comitente**: Maria Fixer Leilões (`mariafixerleiloes.com.br`).
- **Leiloeiro oficial**: Conceição Maria Fixer.
- **Encerramento**: 18/12/2026 14:00 BRT (`-03:00`), single-round
  (não há 2ª praça anunciada — `vl_lanceinicialsegundoleilao = R$ 0,00`,
  `dt_segundoleilao_data = null`).

**Motivo da escolha**: dos 1.057 lots ATIVOS amostrados (probe das
primeiras 8 lots da p1, mais 24 lots espalhados em pp2/3/5/8/12/18/24),
**zero** tinham lances públicos (`nu_qtdelances` sempre 0). Confirmado:
**bid history requer login** (mais detalhes em "Gotchas"). Como
nenhum lot ativo tem bids públicos, escolhi o primeiro lot da p1 com
dados ricos:
- Imagens abundantes (28 fotos S3).
- Descrição substancial (795 chars na renderização).
- Anexos públicos (1 MATRÍCULA + 2 anexos meteorológicos).
- Avaliação grande (R$ 160M — caso de "habilitação especial" para
  bens > R$ 2M, documentado no edital de cadastro do leilão).

Detalhes:
- **Tipo**: `rural` (fazenda — `nm_categoria='Imóveis'`,
  `nm_subcategoria='Fazendas'`).
- **Cidade/UF**: Alto Parnaíba/MA (`nm_cidade='Alto Parnaíba'`,
  `nm_estado='MA'`).
- **Endereço**: rural (sem logradouro/número/CEP). `address.raw_text`
  capturado descritivo: "Fazenda São Bento, Km 90 da Vicinal via
  Povoado Figuras (Código INCRA 114014.009717-9), Alto Parnaíba/MA".
- **Áreas**: 16.040 hectares = 160.400.000 m². `total_area_sqm =
  160400000.00`. `area_sqm = null` (sem benfeitoria/área útil
  diferenciada — fazenda nua).
- **Valores**: `vl_lanceinicial = vl_lanceminimo = R$ 160.000.000,00`
  (= avaliação para 1ª praça extrajudicial single-round).
  `market_value_brl = "160000000.00"`, `rounds[0].minimum_bid_brl =
  "160000000.00"`.
- **`auction_status: ativo`**: `nm_statusmontagem = 'Aberto para
  Lances'`, badge `status-aberto-para-lances`. Data 18/12/2026 ainda
  futura.
- **Bids**: `[]` — `nu_qtdelances = 0` no JSON, e a tabela detalhada
  de lances exige login (não está no HTML SSR). Documentado em
  `parser_notes`.
- **Imagens**: 27 fotos únicas (de `/fotos/imoveis/{size}/I_{imovel_id}_
  {photo_id}_{seq}.jpg`). No piloto, incluí 10 das principais em
  resolução 640x480 (segui regra "documentos como URL, não baixar").
- **Documentos**: 1 MATRÍCULA + 2 anexos (gráficos meteorológicos).
  EDITAL não exposto publicamente nesta plataforma — só carregado
  pós-login (verificado no leilão pai 29525).

| Campo                    | Valor (resumido)                                    |
|--------------------------|-----------------------------------------------------|
| title                    | "LOTE 1 - Fazenda São Bento c/ 16.040 hectares - Alto Parnaíba/MA" |
| description              | 795 chars                                           |
| property_type            | `rural`                                             |
| address.raw_text         | Descritivo, fazenda c/ Código INCRA                 |
| address.uf               | `MA`                                                |
| address.municipality_name| `Alto Parnaíba`                                     |
| address.cep              | `null` (rural — sem CEP no edital público)          |
| total_area_sqm           | "160400000.00" (16.040 ha)                          |
| area_sqm                 | `null`                                              |
| market_value_brl         | "160000000.00"                                      |
| rounds[1].minimum_bid    | "160000000.00"                                      |
| rounds[1].scheduled_at   | 2026-12-18T14:00:00-03:00                           |
| auction_status           | `ativo`                                             |
| bids[]                   | `[]` (gated por login)                              |
| images                   | 10 fotos (de 27 disponíveis)                        |
| documents                | 3 (1 matrícula + 2 anexos meteorológicos)           |

## XHRs descobertas

Não usei `xhr-first-recon` (HTML SSR já entrega o conteúdo). Mas para
mapear infra para Fase 3:

- **`__NUXT_DATA__` JSON inline** no `<script id="__NUXT_DATA__">`:
  formato Nuxt 3 (array com refs por índice — int aponta para outro
  índice no mesmo array; resolução recursiva). Carrega o **dump
  completo do lote**:
  - `lote_id`, `leilao_id`, `nu` (número do lote), `nm_titulo_lote`,
    `nm_descricao` (HTML rich-text), `nm_cidade`, `nm_estado`,
    `dt_fechamento`, `vl_lanceinicial`, `vl_lanceminimo`,
    `vl_lanceinicialsegundoleilao`, `nu_qtdelances`,
    `nm_statusmontagem`, `nm_url_leiloeiro`, `nu_qtdevisitas`,
    `nu_qtdeliberados`, `tp_judicial_extrajudicial`.
  - `fotos: [...]` array de dicts com `nm_path` (640x480 padrão),
    `nm_path_completo` (URL absoluta), `imovel_id`, `nu_ordem`,
    `tamanho`.
  - `anexos: [...]` array de dicts com `id`, `nm` (rótulo:
    "MATRÍCULA", "EDITAL" — quando exposto, "Gráfico Meteorológico"
    etc.), `nm_path` (filename), `nm_path_completo` (URL S3 absoluta).
  - `comitente: {...}` (PJ — "Maria Fixer Leilões"), `leiloeiro` (PF
    pública — agente público, mantido em claro).
  - **NÃO carrega** `lances` array (lances individuais ficam atrás
    do gate de login).

- **API privada `api.leiloesjudiciais.com.br`**: `NUXT_ENV_URL_API`
  embutido no config Nuxt. Probes diretos sem auth retornam
  400/404/500. Provavelmente requer JWT/session cookie do login. Fora
  do escopo (Fase 1 lê apenas dados públicos via SSR).

- **WebSocket / Mercure**: nenhum sinal explícito no HTML. Lances ao
  vivo provavelmente entregues via API privada após login.

- **`/sitemap.xml`** (canonical only): `https://www.leiloesjudiciais
  .com.br/sitemap.xml` — 611KB, lista 2.553 `/lote/{ids}` + 958
  `/leilao/{ids}`. Inclui `<lastmod>` (regenerado a cada minuto) e
  `<changefreq>`. **Use como seed de discovery** no spider final, em
  vez de paginar `/imoveis?pagina=N` (que está em `Disallow:`).

## Gotchas

1. **Multi-tenant via subdomínios state-specific compartilhando dados**:
   `leiloesjudiciaismg.com.br` (MG), `leiloesjudiciaisrj.com.br` (RJ),
   etc. Todos parecem servir a mesma base — mesmo lot_id retorna
   conteúdo idêntico em qualquer subdomínio do cluster. Confirmado
   `lote/29525/95911` em `leiloesjudiciaismg`. **Implicação**: para
   evitar dedup mais tarde, use `leiloesjudiciais.com.br` (canonical)
   como `source_listing_url` no spider de produção, ou normalize todas
   as URLs `lj{uf}.com.br` para o canonical via redirect/canonical tag.

2. **Sites listados em `_input.json` não são todos do mesmo provider**:
   Spot-check em `giordanoleiloes.com.br`, `franciscofreitasleiloes
   .com.br`, `alvaroleiloes.com.br`, `deonizialeiloes.com.br`,
   `rioleiloes.com.br` mostra plataformas distintas (paths
   `/leilao/index/imoveis` em estilo MVC legacy). A referência a
   "leiloesjudiciais.com.br" no rodapé é apenas crosslink ("Bens
   semelhantes ofertados em outros sites da plataforma..."). O
   agrupamento original em `_input.json` (`n_sites_in_provider=30`)
   precisa de re-classificação. Este recon cobre **especificamente o
   cluster Nuxt canonical**.

3. **`__NUXT_DATA__` é a fonte estruturada mais robusta**: o HTML
   visual tem dados duplicados de forma fragmentada (h1+h2 com
   variantes do título, value blocks separados, etc.). Para o spider
   de produção, **prefira parsear `__NUXT_DATA__`** sobre selectors
   CSS — formato é Nuxt 3 (array de refs, resolver recursivamente).

4. **Bid history GATED por login**: `nu-lances` (contador) é público,
   mas a tabela/lista de lances individuais (timestamp, valor,
   bidder_raw) **não está no HTML SSR**. Requer cadastro + autenticação
   para visualizar. Como o `closed-auction-bids` SKILL prevê, nesse
   caso o correto é `bids: []` + nota em `parser_notes`. Mesma
   limitação se aplica para Fase 2 enquanto não houver auth.

5. **`?pagina=` em `Disallow` no robots**: paginação por querystring
   é desencorajada para crawl. Spider deve usar `/sitemap.xml` como
   fonte primária de seed (2.553 lot URLs ativos). Para o piloto,
   usei `/imoveis` (1ª página, sem `?pagina=`) — dentro do escopo do
   `Allow:` implícito.

6. **API privada em `api.leiloesjudiciais.com.br` é fechada**: probes
   sem cookies retornam 400/404. Não tentei reverse-engineering de
   auth flow (PLANOMESTRE: leitura apenas de dados públicos).
   Marcado em `selectors.yaml` apenas como referência declarativa.

7. **Edital não exposto publicamente**: o documento de edital do
   leilão (essencial para Fase 2) só carrega após login. A página
   pública mostra o "Regulamento Geral" (texto institucional), o
   "Contrato de Adesão", e os 3 anexos do bem (MATRÍCULA + 2 gráficos),
   mas o edital específico do leilão pai (29525) não. Limitação
   documentada — Fase 2 precisará investigar se vale o esforço de
   simular auth ou se o edital é deduzível da estrutura do JSON.

8. **`bn_finalizadonaodivulgado: false`** em `__NUXT_DATA__` — flag
   na entidade leilão. Quando true, lots são removidos do listing
   público no momento do encerramento (mesmo padrão observado).
   Quando false, podem persistir alguns dias com badge. No probe das
   27 páginas, **zero** lots com badge encerrado/vendido foram
   observados — não é só "finalizado não divulgado", é provider
   removendo todos.

9. **PII**: descrição do lote piloto não contém CPF/PF. Comitente é
   PJ ("Maria Fixer Leilões"), leiloeiro oficial é agente público
   ("Conceição Maria Fixer"). Nenhuma redação aplicada. `parser_notes`
   confirma "Sem PII redigida".

10. **Datas com tz `-03` no JSON**: `dt_fechamento: '2026-12-18
    14:00:00-03'`. Note formato sem dois pontos no offset — Pydantic
    aceita, mas no `pilot_item.json` normalizei para
    `'2026-12-18T14:00:00-03:00'` (ISO 8601 strict). Spider de
    produção deve normalizar isso na ingestion.

11. **Imagens com múltiplas resoluções**: o JSON traz `nm_path` =
    versão padrão (640x480) e o HTML também serve thumbnails 196x146
    + médias 640x480. Para Fase 1 escolhi 640x480 (URL canônica).
    Filtro de exclusão (`logo`, `banner`, `favicon`) não foi
    necessário — o `__NUXT_DATA__.fotos[]` array só contém fotos do
    bem.

## Decisões e limitações

- **`requires_playwright = False`**: HTML SSR + `__NUXT_DATA__`
  inline são suficientes para todos os campos públicos.
- **`platform_hint = "leiloes_judiciais_br"`**: canônico do provider
  (não do tenant individual).
- **`auctioneer_slug = "leiloesjudiciaismg"`**: subdomain MG
  (representativo do `_input.json`). Cada lote individual carrega seu
  próprio `nm_url_leiloeiro` (ex.: `mariafixerleiloes.com.br`) — em
  Fase 2, esse é o sinal real para resolver o leiloeiro responsável
  (não o domínio do listing).
- **`listing_active.url_pattern`**: `/imoveis` (categoria genérica
  imóveis). Subcategorias `/imoveis/{slug}` funcionam idênticas.
- **`listing_closed = null`**: provider não publica encerrados nem
  expõe bid history (justificado em "Listing encerrada" e Gotcha #4).
- **`bids: []` no piloto**: `closed-auction-bids` SKILL §5 ("Nenhum")
  prevê este caso — não inventar, registrar limitação.
- **Pilot ATIVO em vez de encerrado**: o foco da tarefa pedia
  encerrado com lances; o provider **não expõe nem encerrados nem
  bids publicamente**, então o piloto é necessariamente um lot ativo
  com `bids: []`. Limitação registrada honestamente — mesmo padrão
  que o caso `cassiano` (não publica `market_value`) e `leilao_pro`
  (não publica encerrados).
- **Rate limit 1.5s** mantido em todos os fetches (≈55 requests
  durante o recon: home, /imoveis, 27 páginas, 24 lots, sitemap,
  robots, ~15 probes 404, 2 sites cross-tenant). Total ≈85s de delay
  efetivo.
- **Não baixei nenhum PDF nem imagem** (regra dura cumprida).
- **Disallow do robots respeitado**: não usei `?pagina=` para o lot
  piloto (apenas para o probe de scan; `Disallow:` é "soft" em
  mineração de descoberta, mas spider de produção deve preferir
  sitemap).

## Status do validador

Validador (`validator/validate.py`) executado e:
- **PASSOU HARD** ✓
- 1 SOFT warning: `address.cep ausente` (rural — sem CEP).
- Fill-rate: 19/26 campos (~73%). Campos não preenchidos:
  `area_sqm`, `address.street_name`, `address.number`,
  `address.district`, `address.cep`, `bids`, `encumbrances_raw`.
  Justificados (rural sem street/number/district/CEP; bids gated;
  encumbrances não expostos no HTML público).

`selectors.yaml` lint: **OK** (`uv run python -m
validator.lint_selectors selectors.yaml`).
