# soleon

Recon arquitetural do **provider `soleon`** (SOLEON Soluções para
Leilões Online). 116 leiloeiros catalogados em
`data/intermediate/site_analysis.csv` apontam para esta plataforma —
a maior fatia em escopo, à frente de `leilao_pro` (83) e
`suporte_leiloes` (51).

Tenant amostrado para o piloto: **`isaiasleiloes.com.br`** (Isaías
Rosa Ramos Júnior, JUCEMG 831, Patos de Minas/MG) — o representante
declarado em `_input.json`.

Spot-checks adicionais em `leiloesceruli.com.br` (Flávio Duarte
Ceruli, MG), `italoleiloes.com` (Italo Trindade Moura Filho),
`lancese.com.br` (Valério/Carlos Fiel) e `ccjleiloes.com.br` (João
Luiz de França Neto). Já existe um piloto SOLEON-tenant em
`specs/fabio-marlon-machado/` (machadoleiloeiro.com.br/SC); este
recon é complementar — foco em **leilão encerrado com lances**, que
o piloto do Fábio Marlon não cobre (lá o lote piloto é ativo).

## Tech stack & rendering

`site_analysis.csv` (linha 377, isaias) traz: `rendering=hybrid`,
`tech_stack=jQuery; Bootstrap`,
`tech_signals=jquery | bootstrap | server:cloudflare`,
`static_useful_links=182`, `dynamic_useful_links=215`,
`requires_js_for_listings=False`. Confirmado em todos os 5 tenants
amostrados:

- **Server-side rendering** com Bootstrap 4 + jQuery + FontAwesome 5
  sobre Cloudflare. Cards de leilão e detalhes de lote (incluindo
  bid history) renderizados inline. `hybrid` no CSV é leve drift —
  o que existe de "dinâmico" são modais de login + carousels JS,
  não a listagem em si. Para Fase 1 trata-se como **estático**.
- **Plataforma `soleon`** — sinais canônicos:
  - `<meta name="author" content="SOLEON Soluções para Leilões Online">`
  - Footer `<small>Tecnologia SOLEON</small>`
  - Rotas: `/leilao/{leilao_id}/lotes` (lista de lotes do leilão),
    `/item/{lot_id}/detalhes` (detalhe do lote — note: rota
    `/item/`, não `/lote/`), `/leiloes/encerrados` (paginada via
    `?page=N`).
  - Stack inferida: PHP + jQuery (legacy CMS interno), MySQL/
    Postgres (IDs sequenciais, `leilao_id` 4xxx-5xxx, `lot_id`
    20xxx-26xxx, `bem_id` interno 18xxx).
- **CDN externa varia por tenant**:
  - `d2mymldkpl0730.cloudfront.net` em isaias, ceruli, italo,
    lancese, ccj (todos amostrados aqui — provavelmente CDN
    "default" SOLEON).
  - `{hash}.cdn.gocache.net` em machadoleiloeiro.com.br
    (subdomain tenant-specific) — caso já documentado em
    `specs/fabio-marlon-machado/recon.md` com hash
    `b10207a522e5048d`.
  - Path padrão idêntico nos dois CDNs:
    `/bens/{bem_id_padded:010d}/img-{bem_id}-{hash}.{jpg|JPG}` para
    fotos, `/bens/{bem_id_padded}/{kind}-de-leilao-{hash}.pdf` ou
    `/bens/{bem_id}/matricula-do-imovel-{hash}.pdf` para docs.
- **CDN/Hosting**: `server: cloudflare` em todos os tenants. Sem
  proteção JS challenge ou CAPTCHA no acesso público.
- **Idiomas/i18n**: pt-BR fixo. Datas em `DD/MM/YYYY HH:MM` ou
  `HH:MM:SS`, valores em `R$ NN.NNN,NN`.
- **robots.txt** (homogêneo entre tenants amostrados, todos
  usam Cloudflare Managed):
  ```
  User-agent: *
  Content-Signal: search=yes,ai-train=no
  Allow: /
  ```
  Disallows explícitos só para AI trainers conhecidos:
  `Amazonbot, Applebot-Extended, Bytespider, CCBot, ClaudeBot,
  CloudflareBrowserRenderingCrawler, Google-Extended, GPTBot,
  meta-externalagent, OAI-SearchBot, PerplexityBot,
  GoogleOther`. `TodoLeilaoBot/1.0` cai na regra `*`
  (search=yes/ai-train=no); raspagem para indexação pública é
  permitida — respeitado.

**Conclusão**: `requires_playwright = False`. Toda a Fase 1 e Fase 2
podem rodar com `httpx` + `BeautifulSoup` (ou `Scrapy` puro).

## Listing ativa

URL canônica por tenant: **a home `/`** já é a listagem ativa. 40
leilões na home do isaias amostrado, ordem decrescente de
`leilao_id` (mais recente primeiro). Cada card aponta para
`/leilao/{id}/lotes` (lista de lotes do leilão).

Card selector: `a[href*='/leilao/'][href$='/lotes']` — mesmo
selector que o `fabio-marlon-machado` (também SOLEON). Retorna
~3-4 anchors por leilão (logo + título + botão "Ver Lotes" duplicam),
deduplicar por URL canônica antes de enfileirar.

Paginação na home: **`kind: none`**. Todos os 40 cards saem na
primeira request. Tenants menores podem ter <40 leilões ativos; em
nenhum caso amostrado a home foi paginada.

**Filtragem por tipo de imóvel client-side**: existem rotas como
`/lotes/imovel`, `/lotes/imoveis` (busca categórica), mas são
JS-renderizadas e só funcionam pra usuários logados em alguns
tenants. Spider de produção pode ignorar e usar a home como seed.

## Listing encerrada

URL canônica: **`/leiloes/encerrados`** (paginada via querystring
`?page=N`). 48 páginas no isaias amostrado (≈480 leilões encerrados
acumulados); ceruli/italo/lancese provavelmente similar.

Mesmo selector da home funciona aqui. Padrão de cards é idêntico.

> **Cross-tenant gotcha**: alguns leilões no `/leiloes/encerrados`
> de um tenant SOLEON na verdade pertencem a **outro tenant
> SOLEON** — o link aponta pro tenant local mas a página retorna
> `<meta http-equiv="refresh" content="0;url='http://{tenant_slug}.soleon.com.br/leilao/{id}/lotes'">`.
> Esses subdomínios `*.soleon.com.br` na **porta 80 fazem timeout**
> (não respondem). A maneira robusta de seguir é: extrair o slug do
> tenant do redirect, montar a URL HTTPS canônica do tenant
> (`https://www.{tenant_slug}leiloes.com.br/`), e só então seguir.
> Isso confirma que o backend SOLEON é **um único cluster
> compartilhado** por todos os tenants — `leilao_id` é global no
> provider, não por tenant. Para nosso scope (1 tenant amostrado +
> 1 lote piloto), tratamos cada tenant como independente; spider de
> produção precisa lidar com isso (resolução de tenant via
> redirect-following + dedup global por `leilao_id`).

## Pilot lot escolhido

URL: `https://www.isaiasleiloes.com.br/item/22553/detalhes`

Leilão pai: `https://www.isaiasleiloes.com.br/leilao/5067/lotes` —
"IMÓVEL RESIDENCIAL EM ALTO JEQUITIBÁ/MG" (1 lote único), comitente
**TJMG - FÓRUM DE MANHUMIRIM - 2º LEILÃO** (judicial 2ª praça).

**Motivo da escolha**: o foco do recon é leilão encerrado com lances.
Encerrados por status no SOLEON: `vendido` (arrematado), `sem_licitante`
(encerrado deserto), `sustado` (suspenso por decisão judicial). Apenas
`vendido` traz histórico de lances populado. Probe sistemático em 11
leilões de imóvel encerrados (5003, 5044, 5067, 5132, 5147, 5148,
5174, 5045, 5076, 5100, 5108, primeiro lote de cada) revelou:

| leilao_id | lot_id | status         | bids | tipo                     |
|-----------|--------|----------------|------|--------------------------|
| 5003      | 22449  | sustado        | —    | imóvel resid./comercial  |
| 5044      | 22514  | sem_licitante  | —    | sala comercial SP        |
| **5067**  | **22553** | **vendido** | **1** | **imóvel residencial MG (este!)** |
| 5132      | 22680  | sem_licitante  | —    | imóvel residencial MG    |
| 5147      | 22710  | sustado        | —    | imóvel comercial Uberaba |
| 5148      | 22711  | sustado        | —    | imóvel comercial Uberaba |
| 5174      | 22757  | sustado        | 1    | imóvel comercial Maceió  |
| 5045      | 22515  | sem_licitante  | —    | sala comercial SP        |

Apenas 22553 (vendido) e 22757 (sustado) tinham lance. Escolhi
**22553** porque `vendido` reflete o caso terminal canônico
(arrematado) — o estado mais informativo do ciclo de vida; sustado
representa interrupção judicial (suspenso) e tem semântica
diferente.

Detalhes:
- **Lote 001** (single-lot auction). `meta name="description"`
  format: `"Lote 001 - {TÍTULO} (ID {lot_id})  "`.
- **Título**: IMÓVEL RESIDENCIAL EM ALTO JEQUITIBÁ/MG.
- **Tipo**: `casa` (descrição menciona "UMA CASA COM ... 03 QUARTOS,
  UMA SALA, COZINHA, BANHEIRO ...").
- **Endereço bruto**: "RUA EDUARDO DE PAULA GOMES, 14 - GRIPP MOTTA -
  Alto Jequitibá / MG". `cep=null` — o site SOLEON **não publica CEP
  do imóvel**, apenas do escritório do leiloeiro no rodapé. Fase 2
  derivar via geocoding (Google Maps iframe usa o endereço bruto).
- **AVALIAÇÃO**: R$ 90.000,00.
- **Lance Inicial**: R$ 45.000,00 (= 50% da avaliação, padrão
  judicial 2ª praça pós-1ª deserta — Lei 9.514 não se aplica aqui;
  é leilão judicial regido pelo CPC).
- **1 round** (single-praça expostas — site renderiza só "Encerramento:
  17/10/2025 16:30"; a 1ª praça anterior pode ter existido em outro
  leilao_id, não vinculado nesta página).
  - `round_number=2` (justificado pelo título do comitente
    "2º LEILÃO" + Lance Inicial = 50% avaliação).
- **Bids exposed**: 1 lance único — `wallisson`, R$ 45.000,00,
  manual (com configuração de pagamento `25% + 30X` em metadados),
  em **17/10/2025 16:20:14** BRT (10 minutos antes do encerramento
  às 16:30). Capturado em
  `<div class="ult_body"> > div.ultimos-lances-item`.
- **Imagens**: 1 foto única
  (`/bens/0000018341/img-18341-6876466dc1e48.jpg`). Sem placeholder
  `sem-imagem-lote.jpg` neste lote.
- **Documentos**: 2 — matrícula
  (`/bens/0000018341/matricula-do-imovel-...pdf`) + edital
  (`/bens/0000018341/edital-de-leilao-...pdf`). Ambos via CDN
  cloudfront público; spider de produção **não baixa** os PDFs (regra
  dura) — apenas os mantém como URL referência.
- **`auction_status: "arrematado"`** (badge `<div class="label_lote
  vendido">Vendido</div>` → mapeia para canônico `arrematado`).

| Campo                    | Valor (resumido)                                   |
|--------------------------|----------------------------------------------------|
| title                    | "Lote 001 - IMÓVEL RESIDENCIAL EM ALTO JEQUITIBÁ/MG (ID 22553)" |
| description              | 1090 chars (descrição completa + comitente/processo/comarca) |
| property_type            | `casa`                                             |
| address.raw_text         | "RUA EDUARDO DE PAULA GOMES, 14 - GRIPP MOTTA - Alto Jequitibá / MG" |
| address.uf               | `MG`                                               |
| address.municipality_name| `Alto Jequitibá`                                   |
| address.district         | `GRIPP MOTTA`                                      |
| address.cep              | null (site não publica CEP do imóvel)              |
| total_area_sqm           | "240.00"                                           |
| area_sqm                 | null (sem distinção área útil/construída)          |
| market_value_brl         | "90000.00"                                         |
| rounds[0]                | round 2, R$45.000, encerrado 17/10/2025 16:30 BRT  |
| auction_status           | `arrematado`                                       |
| bids[]                   | 1 (wallisson, R$45k, 17/10/2025 16:20:14 BRT)      |
| images                   | 1                                                  |
| documents                | 2 (matrícula + edital)                             |
| encumbrances_raw         | [] (descrição não traz cláusulas de ônus)          |

## XHRs descobertas

Não usei `xhr-first-recon` — site é estático e os lances já vêm no
HTML inicial. Não há SSE/WebSocket público no SOLEON (diferente do
`leilao_pro` que usa Mercure SSE). Atualização real-time de lances
durante leilão ao vivo provavelmente via polling jQuery + endpoint
interno (`/painel/...` — Disallow no robots, fora do escopo).

## Gotchas

1. **Multi-tenant homogêneo, mas com cross-tenant aggregation**:
   116 sites SOLEON rodam o mesmo template PHP+jQuery — selectors
   no `selectors.yaml` são portáveis entre tenants (verificado em
   5 amostrados: isaias, ceruli, italo, lancese, ccj +
   machadoleiloeiro do recon anterior). MAS o backend é um cluster
   compartilhado: `leilao_id` é global no provider, e o
   `/leiloes/encerrados` de um tenant **inclui leilões de outros
   tenants** com redirect via `<meta refresh>` para o subdomain
   `*.soleon.com.br` correspondente. Spider de produção precisa
   resolver tenant via redirect-following.

2. **`*.soleon.com.br` na porta 80 timeout**: o backend SOLEON
   redireciona via `<meta http-equiv="refresh" content="0;url='http://{slug}.soleon.com.br/...'">`
   (HTTP, não HTTPS!). Esses subdomínios não respondem na porta 80
   (timeout 30s). A solução é mapear para o domínio canônico do
   tenant via HTTPS (`https://www.{slug}leiloes.com.br/...` ou
   variações), o que requer um lookup do tenant. Para o piloto,
   evitei esse caminho — peguei um leilão que NÃO redireciona
   (leilao_id local do isaias). Spider em escala precisa do mapeamento.

3. **CDN varia por tenant**: cloudfront vs gocache. Path interno é
   o mesmo (`/bens/{bem_id_padded}/...`), só muda o host. Spider
   pode usar regex `://[^/]+/(bens|leiloes)/0+\d+/` para extrair
   bem_id+kind sem hard-codar host.

4. **Três identificadores distintos**: `leilao_id` (5067, agrupador
   na URL `/leilao/{id}/lotes`), `lot_id` (22553, na URL canônica
   `/item/{id}/detalhes`) e `bem_id` (18341, padded para 10 dígitos
   no path do CDN `/bens/0000018341/`). Spider precisa guardar os
   três para reconciliação cross-leilão e download de assets.

5. **Username/handle: público vs obfuscado por status**: lotes
   `vendido` mostram username em **claro** (`wallisson`, `mmagni`-
   like). Lotes `aberto_lance` (ativos, em andamento) tipicamente
   **obfuscam** o username (`s************s`) para esconder durante
   o leilão ao vivo, expondo apenas após encerramento. Confirmado em
   item 22726 (vendido, vehicle, isaias, encerrado em 24/02/2026):
   header mostra `s************s` mas pode ser feature do tenant
   ou bug — em 22553 (também vendido) mostra `wallisson` sem
   obfuscação. Inconsistência do provider; spider deve aceitar
   ambos os formatos.

6. **PII presente no detalhe**: bloco "Detalhes do Lote" expõe
   `Executado: NOME COMPLETO PF` em leilões judiciais. Fase 1 redige
   para `[PF]` no `pilot_item.json`. Comitente (TJMG, JFRN, varas)
   é PJ pública — mantém. Vara/Comarca são metadados públicos. CPF
   não é exposto neste tenant; outros tenants podem expor — sempre
   redigir.

7. **Status taxonomy**: SOLEON usa 4 valores no
   `<div class="label_lote {status}">`:
   | classe         | display      | canônico (PilotItem)   |
   |----------------|--------------|------------------------|
   | aberto_lance   | Aberto p/ Lances | ativo               |
   | sem_licitante  | Sem Licitante  | encerrado            |
   | vendido        | Vendido        | arrematado           |
   | sustado        | Sustado        | suspenso             |
   Não vi badges `cancelado` no recon — pode ser que o backend use
   outra classe pra isso, ou o estado simplesmente não é exposto.

8. **Single-round na página é a regra**: SOLEON renderiza apenas a
   praça atual no detalhe. Para leilões judiciais com 1ª praça
   deserta + 2ª praça em outro `leilao_id`: o número da praça vem
   do título do comitente ("2º LEILÃO"), não de campos
   estruturados. Para alienação fiduciária Lei 9.514: leilão pode
   ter 1º e 2º round na mesma página — então o `fabio-marlon-machado`
   tem 2 rounds, mas em isaias o leilão judicial expõe só 1.
   Mantive `round_number=2` neste pilot porque o comitente
   declara explicitamente "2º LEILÃO".

9. **Documento `kind` heurística**: no SOLEON o nome do arquivo é
   semântico (`matricula-do-imovel-...pdf`, `edital-de-leilao-...pdf`),
   não o texto do `<a>` (que é só "MATRÍCULA DO IMÓVEL", "EDITAL DE
   LEILÃO" — geralmente match com nome). Spider pode usar regex
   no path do CDN: `matricula` → kind=matricula, `edital` → edital,
   `laudo` → laudo, `certidao` → certidao.

10. **Bid history vazio em encerrados sem licitante**: o template
    `<div class="ult_body">` está sempre presente, mas só populado
    em lotes vendidos. Em `sem_licitante`/`sustado`, `ult_body`
    fica vazio. `bids[]=[]` é comportamento legítimo, não bug.

## Decisões e limitações

- **`requires_playwright = False`**: HTML estático suficiente.
- **`platform_hint = "soleon"`**: canônico, sem variantes
  observadas entre os 5 tenants amostrados + 1 documentado em
  recon anterior.
- **`auctioneer_slug = "soleon"`** no piloto (não isaias): este é
  um recon **arquitetural** do provider, não do leiloeiro
  individual. Vivemos em `specs/_providers/soleon/`. O input.json
  aponta isaias como representativo; piloto efetivo em isaias por
  ser único tenant amostrado com lance público em imóvel arrematado.
- **`listing_active.url_pattern`**: home (`/`). Não usei
  `/lotes/imovel` (rota JS, com gating de login em alguns tenants).
- **`listing_closed.url_pattern`**: `/leiloes/encerrados` com
  paginação `?page=N` (48 páginas no isaias).
- **`bids` capturado**: 1 lance, com timestamp + valor + handle.
  Sem CPF a redigir; handle (`wallisson`) mantido por ser público.
- **PII redigida**: 1 nome PF (`Executado: DEUZELI FIDELIS` →
  `[PF]` no `description` do JSON). HTML salvo em
  `pilot_source.html` fica intocado (proveniência), apenas o JSON
  estruturado é redigido (PLANOMESTRE §4).
- **`address.cep = null`**: SOLEON não publica CEP do imóvel.
  Único SOFT warning. Fase 2 derivar via geocoding do
  `address.raw_text`.
- **`area_sqm = null`**: descrição não distingue área útil de
  total. `total_area_sqm=240.00` ("TERRENO MEDINDO 240 M2"). Mesma
  decisão honesta do recon do `fabio-marlon-machado`.
- **Rate limit 1.5s** mantido em todos os fetches (~25 requests
  ao longo do recon — robots, home, encerrados pp 1-5, ~12 leilões
  individuais sondados, 4 detalhes de tenants extras para
  confirmar SOLEON). Total ≈37s de delay efetivo.
- **CDN não consultado**: zero requests ao
  `d2mymldkpl0730.cloudfront.net`; URLs de imagens/documentos
  saíram do HTML do detail.
- **Não baixei nenhum PDF nem imagem** (regra dura).
- **Tenant cross-resolution não implementado** (timeout em
  `*.soleon.com.br:80`): documentado como gotcha para Fase 2.

## Status do validador

`validation.json::passed_hard = true`, **1 SOFT warning**
(`address.cep ausente` — limitação do provider). 21 dos 25 campos
do fill-rate preenchidos (84%); zerados:
- `area_sqm` (sem distinção útil/construída — justificado);
- `address.complement` (descrição não traz complemento separado);
- `address.cep` (provider não publica);
- `encumbrances_raw` (descrição neste lote judicial não traz
  cláusulas de ônus explícitas — caso típico de leilão judicial
  imóvel residencial; alienação fiduciária Lei 9.514 traria).

Validador passou na **1ª tentativa**.
