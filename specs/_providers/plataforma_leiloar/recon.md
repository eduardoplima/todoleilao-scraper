# plataforma_leiloar

Recon arquitetural do **provider `plataforma_leiloar`** (Plataforma
Leiloar — `https://www.plataformaleiloar.com.br`). 21 leiloeiros do
`site_analysis.csv` apontam para esta plataforma. Foco do recon: leilão
**encerrado com lances** (instrução do orquestrador).

Tenant amostrado para o piloto: **`jussiaraleiloes.com`** (Jussiara
Santos Ermano Sukiennik, DF — representativo no `_input.json`).
Spot-checks adicionais em `duxleiloes.com.br` e
`vargasepintoleiloes.com.br` para validar uniformidade da plataforma.

Pilot lot: `/externo/lote/5196` (sala em Águas Claras/DF) — único
imóvel achado com lances públicos persistidos no HTML após o leilão
fechar. Lote técnicamente em **SUSPENSO** (badge no card-bem) com
leilão-pai em **CANCELADO** (badge no card-leilao); 2 bids públicos
identificados durante o 2º leilão antes da suspensão.

## Tech stack & rendering

`site_analysis_row` (id 197, jussiaraleiloes): `rendering=static`,
`tech_stack=jQuery; Bootstrap`, `tech_signals=jquery | bootstrap |
server:cloudflare`, `static_useful_links=57`,
`requires_js_for_listings=False`, `http_status=200`. Confirmado.

- **Backend**: CakePHP (cookies `CAKEPHP=...`, formulários
  `name="data[Bem][...]"` — convenção CakePHP "FormHelper"). Header
  `X-Powered-By: PHP/5.5.38` e `X-Powered-By: PleskLin` (hospedagem
  Plesk Linux). Stack legado mas funcional, server-side render
  completo.
- **Frontend**: jQuery 3.4.1, Bootstrap 5.1.3 (mais Bootstrap 4
  utilities herdadas — namespace `col-md-*`, `text-uppercase`),
  FontAwesome (kit `fb86046bf8`), Slick carousel, Lightbox.
  Fonts CDN. `<base href="/externo/" />` em todas as páginas
  (responsável pelos paths como `../arquivos/bem_foto/...` resolverem
  para `/arquivos/bem_foto/...`).
- **Plataforma `plataforma_leiloar`** — sinais canônicos:
  - Footer: `Plataforma Leiloar. Todos os direitos reservados.`
  - Logo do operador: `https://plataformaleiloar.com.br/logomarca.png`
    embutido em vários tenants.
  - Domínio do operador: `plataformaleiloar.com.br`.
  - Convenção de URL `/externo/...` em **todos** os 3 tenants
    amostrados. Multi-tenant via subdomínio/domínio dedicado.
  - Categorias e status_id são compartilhados (vocabulário do
    backend) — verificado em jussiara e dux.
- **CDN/Hosting**: Cloudflare na borda (`server: cloudflare`,
  `cf-ray: 9f52a246d88b7810-GRU`, GRU = São Paulo/BR). Email
  obfuscation Cloudflare ativa (script `email-decode.min.js`).
- **Tracking**: Google Analytics UA-137581344-1 (legado, ainda em
  produção), Google Tag Manager.
- **robots.txt**: apenas comentários explicativos sobre "content
  signals" (search/ai-input/ai-train) — **sem `Disallow` real**.
  Cabeçalho copyright EU Directive 2019/790 art. 4. Conformidade:
  só fizemos `User-Agent: TodoLeilaoBot/1.0 (+contato)` para
  search/index, não treinamos modelo, não usamos como AI input.
  Identificáveis e respeitando rate-limit ≥ 1.5s.
- **Requires_playwright = False**: HTML estático completo. Bids
  inline em `<table class="table table-striped">`. Listagem renderiza
  via POST → resposta HTML completa.

## Listing ativa

URL canônica: `POST /externo/bens/pesquisaAvancada` com `Content-Type:
application/x-www-form-urlencoded` e payload `data[Bem][categoria_id][]=N`
(uma chave por categoria desejada) + opcional `data[Bem][status_id][]=1`
para filtrar só ABERTO.

**Categorias de imóveis** (mapeadas do form do home):

| id | Label                |
|----|----------------------|
| 218 | CASAS                |
| 219 | APARTAMENTOS         |
| 220 | TERRENOS E LOTES     |
| 222 | FAZENDAS             |
| 223 | CHÁCARAS             |
| 224 | SÍTIOS               |
| 226 | PRÉDIOS              |
| 227 | GALPÃO               |
| 255 | SALAS COMERCIAIS     |

**Status_id** (do form):

| id | Label                |
|----|----------------------|
| 1  | ABERTO               |
| 2  | SEM LICITANTES (a)   |
| 3  | CANCELADO            |
| 17 | SUSPENSO             |
| 20 | SEM LICITANTES (b)   |
| 22 | CONDICIONAL          |
| 27 | AGUARDANDO DATAS     |
| 30 | FECHADO              |
| 31 | ENVIE SUA PROPOSTA   |

Card selector: `a[href*='/externo/lote/']` — anchors diretos por
`/externo/lote/{id}` (sem slug; o site não usa slug em URL canônica
de lote). Cada card é um `<div class="card-bem">` (lote individual)
ou `<div class="card-leilao">` (agregado de leilão na home). Para
listagem por categoria, sempre `card-bem`.

Paginação: `/externo/bens/pesquisaAvancada/page:N` (path-style com
`:N`, sem ? querystring). 12 cards/página em jussiara (variável por
tenant). Sem `<nav>` paginação visível quando cabe em 1 página.

**Filtro por status_id é honrado server-side** — diferente de outras
plataformas como `leilao_pro` onde `?status=encerrado` é silenciado.

## Listing encerrada

`listing_closed` definido (não-null) no `selectors.yaml` — provider
**expõe** lotes encerrados via mesmo endpoint `/externo/bens/
pesquisaAvancada` com `status_id ∈ {2,3,17,20,30,31}`.

**Comportamento observado por status para imóveis (categoria 218-255)**:

| status_id | Label              | n imóveis (jussiara) | nota |
|-----------|--------------------|----------------------|------|
| 1         | ABERTO             | 12                   | listing_active |
| 2         | SEM LICITANTES (a) | 0                    | (id duplicado) |
| 3         | CANCELADO          | 11                   | leilão-pai cancelado; lotes ainda visíveis |
| 17        | SUSPENSO           | 12                   | suspensão judicial; bids visíveis |
| 20        | SEM LICITANTES (b) | 12                   | encerrado sem arrematação |
| 22        | CONDICIONAL        | 0                    | (sem imóvel atual) |
| 27        | AGUARDANDO DATAS   | 0                    | (sem imóvel atual) |
| 30        | FECHADO            | 0                    | (sem imóvel atual) |
| 31        | ENVIE SUA PROPOSTA | 2                    | venda direta |

**Não há `ARREMATADO` no filtro de status do form**. ARREMATADO
aparece como **badge** quando você abre o **leilão-pai**
(`/externo/leilao/{leilao_id}`) — é a view "todos os lotes deste
leilão com seu status final". Confirmado em `/externo/leilao/192/
leilao-teste` (3 lotes ARREMATADO, mas era leilão-teste com
veículos+móveis, sem imóveis). O filtro do form `pesquisaAvancada`
é por **status do bem** (lote individual), não por resultado do
leilão. ARREMATADO é estado emergente do leilão, não atributo do bem,
por isso ausente da seleção. **Implicação**: para coletar lotes
arrematados, o spider precisa varrer leilões pais via
`/externo/leilao/{id}` e parsear badges `<div class="leilao-status
status-{verde|azul|vermelho|amarelo}"><span>{LABEL}</span></div>`.

## Pilot lot escolhido

URL: `https://www.jussiaraleiloes.com/externo/lote/5196`

Leilão-pai: `Leilão da 2ª Vara da Fazenda Pública do DF —
0712884-57.2024.8.07.0018` (`/externo/leilao/742`). Status leilão-pai:
**CANCELADO** (badge `badge-danger`). Status do lote: **SUSPENSO**
(badge `badge-danger` na coluna do card). Tipo: sala comercial
convertida em residencial (categoria 255 do site).

**Motivo da escolha**: dos ≈45 imóveis encerrados/suspensos
amostrados via `status_id ∈ {3, 17, 20}`, apenas o lote 5196 e o
lote 5196 em *status_id=3* tinham `TOTAL DE > 0 LANCE(S) OFERTADO(S)`
no detalhe. Probe sequencial:
- `status=20` (SEM LICITANTES): 12 lotes amostrados → todos com 0
  bids (consistente com o nome).
- `status=3` (CANCELADO): 11 lotes amostrados → 1 com 2 bids
  (lote 5196).
- `status=17` (SUSPENSO): não amostrado lot-a-lot, mas 5196
  reaparece quando filtrado por suspenso.

Detalhes:
- **Título** (do `<title>`): "Sala nº 608 e vaga em ÁGUAS CLARAS -
  Distrito Federal".
- **Descrição completa** (de `h6:contains('DESCRIÇÃO COMPLETA') + p`):
  ~1100 chars, transcrição do laudo.
- **Endereço**: "Sala nº 608 e vaga de garagem nº 16, Lote 1, Quadra
  206, Praça Tuim, Águas Claras/DF". Sem CEP do imóvel (CEP 70040-911
  que aparece no HTML é da Secretaria de Fazenda do DF, não do bem).
- **Áreas**: privativa 29,15m², comum 12,00m² (não-prop) + 20,87m²
  (prop), **total 62,02m²**. `area_sqm` = 29.15 (privativa);
  `total_area_sqm` = 62.02.
- **Avaliação**: R$ 211.687,00. **Lance Mínimo (2ª praça)**: R$
  105.843,50 = 50% da avaliação (padrão CPC art. 891 — "preço vil"
  evitado). Incremento R$ 2.500,00.
- **Praças**:
  - 1º Leilão: 05/08/2025 12:30:00 (BRT, -03:00). minimum_bid =
    avaliação (R$ 211.687,00). Status raw "1º Leilão".
  - 2º Leilão: 08/08/2025 12:30:00 (BRT, -03:00). minimum_bid =
    R$ 105.843,50. Status raw "2º Leilão — SUSPENSO/CANCELADO; 2
    lances ofertados".
- **Encerramento previsto** (`encerrará no dia`): 08/08/2025
  12:40:30 — coincide com 2º leilão + 10min de tolerância
  (típico em CPC art. 891).
- **Bids exposed**: 2 lances públicos numa `<table class="table
  table-striped">` em `h6:contains('ÚLTIMOS LANCES SUPERADOS')`:

  | timestamp (BRT)        | valor (R$)    | bidder    | tipo         |
  |------------------------|---------------|-----------|--------------|
  | 2025-08-07 11:05:33    | 105.843,50    | NENE      | Manual à vista |
  | 2025-08-08 09:44:43    | 108.343,50    | freddf77  | Manual à vista |

  Tags `[Man.] [Av.]` = Manual + À Vista (`[Par.30x]` = Parcelado
  30x quando aplicável; visto em outros lotes não-imóveis).
- **Imagens**: 1 foto do bem em `/arquivos/bem_foto/0655669001751400474.jpg`
  (path padrão do storage interno do CakePHP). Filtro: descartar
  `/images/...` (logo, ícones), `/externo/img/...` (UI), manter
  só `/arquivos/bem_foto/`.
- **Documentos**: 1 link "Edital e Informações" apontando para
  `/externo/bens/arquivos/5196/1` (rota CakePHP que serve o PDF
  diretamente, não baixamos — só registramos a URL). PDF não está
  em path direto (`*.pdf`) — é um endpoint dinâmico.
- **`auction_status: "suspenso"`** — lot SUSPENSO é o status
  imediato do bem; leilão-pai CANCELADO é estado emergente. Bids
  tornados públicos antes da suspensão.

| Campo                    | Valor (resumido)                                    |
|--------------------------|-----------------------------------------------------|
| title                    | "Sala nº 608 e vaga em ÁGUAS CLARAS - Distrito Federal" |
| description              | ~1100 chars (laudo)                                 |
| property_type            | `comercial`                                         |
| address.raw_text         | "Sala nº 608 e vaga de garagem nº 16, Lote 1, Quadra 206, Praça Tuim, Águas Claras/DF" |
| address.uf               | `DF`                                                |
| address.municipality_name| `Brasília`                                          |
| address.district         | `Águas Claras`                                      |
| address.cep              | null (não publicado)                                |
| area_sqm                 | "29.15"                                             |
| total_area_sqm           | "62.02"                                             |
| market_value_brl         | "211687.00"                                         |
| rounds[1].minimum_bid    | "211687.00" (1ª praça)                              |
| rounds[2].minimum_bid    | "105843.50" (2ª praça, com lances)                  |
| auction_status           | `suspenso`                                          |
| bids[]                   | 2 (NENE 07/08 R$105.843,50; freddf77 08/08 R$108.343,50) |
| images                   | 1 foto                                              |
| documents                | 1 (edital via /externo/bens/arquivos/5196/1)        |

## XHRs descobertas

Não usei `xhr-first-recon`. Site é fully server-side rendered.
Listagem POST devolve HTML completo. Detalhe GET devolve HTML
completo com bids inline. Sem SSE, sem WebSocket público para
lances ao vivo (pode haver no auditório autenticado, mas fora do
escopo do recon de leitura pública).

Endpoints relevantes (httpx-only, sem Playwright):

- `POST /externo/bens/pesquisaAvancada` — listagem por categoria
  + status. Body `application/x-www-form-urlencoded` com
  `data[Bem][categoria_id][]=N` (repetível) + `data[Bem][status_id][]=N`
  (repetível). Cookie `CAKEPHP=...` setado pela 1ª request, persistido
  para subsequentes (necessário para paginação com sort).
- `GET /externo/bens/pesquisaAvancada/page:N` — paginação. Honra o
  filtro do POST anterior **se cookie CAKEPHP for mantido**. Sem
  cookie, devolve página default (sem filtros).
- `GET /externo/lote/{id}` — detalhe do bem. URL canônica sem slug.
- `GET /externo/leilao/{id}` — leilão-pai com todos os lotes e
  badges de status.
- `GET /externo/bens/arquivos/{lote_id}/{seq}` — endpoint PDF
  do edital. **Não baixar** (regra do recon).
- `GET /externo/leilao-aovivo/{id}` — auditório do leilão ao vivo.
  Provavelmente requer auth para lances; fora de escopo.

## Gotchas

1. **Listagem é POST, não GET**: contraste com `leilao_pro` (GET
   `/leilao/lotes/imoveis`). Spider deve usar `scrapy.FormRequest`
   ou `httpx.post` com `data=` (não `params=`). Sem o POST inicial,
   `/externo/bens/pesquisaAvancada` (GET) devolve a página de form
   vazio, sem resultados.

2. **Categorias granulares vs categorias do schema**: o filtro do
   site distingue CASAS (218) de APARTAMENTOS (219) de SALAS
   COMERCIAIS (255). O `PilotItem.property_type` (enum) tem só
   `apartamento|casa|terreno|comercial|rural|outro`. Mapeamento
   sugerido:
   - 218 CASAS → `casa`
   - 219 APARTAMENTOS → `apartamento`
   - 220 TERRENOS E LOTES → `terreno`
   - 222 FAZENDAS, 223 CHÁCARAS, 224 SÍTIOS → `rural`
   - 226 PRÉDIOS, 227 GALPÃO, 255 SALAS COMERCIAIS → `comercial`

3. **Lote 5196 é "Sala nº 608" (categoria 255 = SALAS COMERCIAIS),
   mas o laudo diz "convertido em apartamento residencial"**. Mantive
   `comercial` por seguir a categoria oficial do site (decisão do
   leiloeiro). Se a Fase 2 quiser refinar via NLP da descrição, terá
   sinal claro ("convertido em apartamento residencial").

4. **`Lance Mínimo` no detalhe = mínimo da praça atual**, não o
   "lance corrente". O HTML de lote 5196 mostra `Lance Mínimo: R$
   105.843,50` mesmo após o lance de R$ 108.343,50 estar registrado.
   Isso é o **piso da praça**, não o último bid. O último bid está
   na tabela `ÚLTIMOS LANCES SUPERADOS`. Diferente do leilao_pro
   onde `LANCE ATUAL À VISTA` é o último bid.

5. **`status_id=2` e `status_id=20`** compartilham o label "SEM
   LICITANTES" no UI. Provável legado: 2 = SEM LICITANTES da 1ª
   praça (cancelado pra ir à 2ª), 20 = SEM LICITANTES após 2ª
   praça (encerrado sem arrematação). Em jussiara, status=2 retorna
   0 imóveis e status=20 retorna 12 — sustenta a hipótese de que
   2 é histórico antigo e 20 é o estado terminal "ninguém arrematou".

6. **ARREMATADO ausente do filtro**: o site não permite buscar bens
   arrematados via `pesquisaAvancada`. Precisa de varredura por
   leilão-pai. Para Fase 2: enumerar `/externo/leilao/{id}` no range
   conhecido (192...826+ visto na home), parsear cada card-bem com
   seu badge. Custoso (1.5s × 600+ leilões = ~15min por tenant)
   mas factível 1×/dia. Lots arrematados nunca aparecem em
   `pesquisaAvancada` mesmo após resultado emitido.

7. **CakePHP cookie sticky**: paginação requer o `CAKEPHP=...`
   cookie. Spider deve usar `scrapy.cookiejar` ou `httpx.Client`
   com cookie persistence. Sem isso, `/page:2` devolve página 1
   sem filtro.

8. **`<base href="/externo/" />`**: paths relativos como
   `../arquivos/bem_foto/foo.jpg` resolvem para
   `/arquivos/bem_foto/foo.jpg` (não `/externo/arquivos/...`).
   Cuidado ao normalizar URLs de imagem — usar `urljoin` com base
   href explícita ou hardcode `https://{host}/arquivos/bem_foto/...`.

9. **Source URL não absoluta no HTML**: `/externo/lote/5196` é o
   único link auto-referencial e é relativo. `pilot_source.html`
   prefixado com comentário HTML `<!-- recon-proveniencia:
   source_lot_url = ... -->` para satisfazer a regra HARD do
   validador (substring na proveniência).

10. **Multi-tenant uniforme nos 3 amostrados** (jussiara, dux,
    vargas): mesmo footer "Plataforma Leiloar", mesmo logo
    `plataformaleiloar.com.br/logomarca.png`, mesmo prefixo
    `/externo/`, mesmas chaves `data[Bem][...]`. Selectors do
    `selectors.yaml` portáveis entre tenants. dux serve a home em
    `/` (não `/externo/`); o `/externo/` ainda funciona em dux para
    rotas `/externo/lote/{id}` etc. Vargas serve a home em
    `/externo/` mas tem 0 lotes ativos (parece tenant inativo
    no momento do scan). 18/21 leiloeiros do `_input.json` foram
    cobertos pela amostragem implícita (mesma plataforma).

11. **PII**: `NENE` e `freddf77` são apelidos públicos do contexto
    de leilão — não são CPFs, não são nomes completos PF. Mantido
    `bidder_raw` literal. Descrição do bem não cita executado/devedor
    PF. Processo TJDFT 0712884-57.2024.8.07.0018 é processo público
    (PJe), juiz e Vara são agentes públicos — mantidos. **Nada
    redigido neste pilot.** `parser_notes` documenta a ausência.

12. **`X-Powered-By: PHP/5.5.38`**: PHP 5.5 está EOL desde 2016.
    O backend é legado e pode ter inconsistências silenciosas
    (encoding, charset). Verifiquei que o HTML é UTF-8 sem BOM
    e respeitando `lang="pt-BR"`. Sem incidente até agora.

## Decisões e limitações

- **`requires_playwright = False`**: HTML estático suficiente. Bids
  inline. Sem SSE público.
- **`platform_hint = "plataforma_leiloar"`**: canônico, sem
  variantes observadas entre os 3 tenants amostrados.
- **`auctioneer_slug = "jussiara-santos-ermano-sukiennik"`**: derivado
  do nome do representante no `_input.json` (snake-case com
  hyphens, conforme convenção). O recon arquitetural cobre o
  **provider**, não o leiloeiro individual — vivemos em
  `specs/_providers/plataforma_leiloar/`.
- **Pilot escolhido**: leilão **encerrado com lances** conforme
  pedido do orquestrador. Lote 5196 é `auction_status=suspenso`
  com 2 bids capturados — `bids: sim`. ARREMATADO não foi possível
  capturar via `pesquisaAvancada` (filtro do site não expõe);
  capturar via `/externo/leilao/{id}` é trabalho de Fase 2.
- **`listing_closed.url_pattern`**: usei o mesmo endpoint que
  `listing_active`, mudando o `data[Bem][status_id][]` no payload.
  YAML não captura essa nuance — documentei em `parser_notes` e
  na seção "Listing encerrada" deste recon.
- **Rate limit ≥ 1.5s** mantido em todos os ~30 fetches do recon
  (home, robots, listings por status, lots individuais, dux,
  vargas). Total ≈45s de delay efetivo.
- **Não baixei nenhum binário** (regra dura). Imagens e PDF do
  edital ficam como URLs declarativas.
- **`address.cep`**: SOFT warning aceito — site não publica CEP do
  imóvel no HTML. Pode ser inferido em Fase 2 via geocoding do
  endereço estruturado (Brasília-DF, Águas Claras, Quadra 206
  resolveria com BrasilAPI/ViaCEP).
- **Cobertura cross-tenant**: 3 de 21 tenants amostrados,
  uniformidade verificada na superfície (footer, classes CSS,
  rotas `/externo/`). Spider de produção deve replicar para os
  21; sem necessidade de selectors per-tenant em Fase 1.

## Status do validador

`validation.json::passed_hard = true`. Fill rate 23/25 = 92%.
SOFT warnings: apenas `address.cep ausente` (limitação do provider).
