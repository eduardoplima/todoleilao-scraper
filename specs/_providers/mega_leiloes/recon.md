# mega_leiloes

Recon arquitetural do **provider `mega_leiloes`** (Mega Leilões —
`https://www.megaleiloes.com.br`). 2 sites em
`data/intermediate/site_analysis.csv` apontam para esta plataforma
(operada centralmente, não multi-tenant): o leiloeiro principal
**FERNANDO JOSÉ CERELLO GONÇALVES PEREIRA** (`/`) e a filial MS
**Milena Rosa Di Giacomo Adri** (`/ms`). Ambos compartilham o mesmo
backend, base de leilões e estrutura de URL.

Pilot escolhido em **leilão ENCERRADO/ARREMATADO** (X122302 dentro
de ML33575 — Banco Itaú AF Imóveis Remanescentes 23/04/2026), com
8 lances públicos extraídos do `<table>` paginado em `/tab-bids`.

## Tech stack & rendering

`site_analysis.csv` (linha 322) traz: `rendering=hybrid`,
`tech_stack=jQuery; Bootstrap; Mega Leilões`,
`tech_signals=jquery | bootstrap | megaleiloes | server:cloudflare`,
`static_useful_links=521`, `dynamic_useful_links=748`,
`requires_js_for_listings=False`.

Confirmado em probe direto:

- **Server-side rendering (Yii2/PHP)**. HTML inicial já contém todos
  os cards de lote com `card-status`, `card-instance-value`,
  `card-instance-info` populados. Listing e detalhe rodam puramente
  com `httpx + BeautifulSoup`.
- **Plataforma proprietária Mega Leilões** — sinais canônicos:
  - Comentário HTML topo: `Desenvolvido por Othis desde 2011`
  - `<meta property="og:site_name" content="Mega Leilões">`
  - `data-pjax`, `data-pjax-container`, `data-pjax-timeout` →
    extension `yiisoft/yii2-pjax` (Yii2 framework)
  - `class="grid-view"` + `summary` "Exibindo 1-5 de 8 itens" →
    Yii2 `GridView` widget (paginação via
    `?pagina-lances=N` para tabela de lances; `?pagina=N` para
    listing de lotes — paths separados, mesmo padrão)
  - CDN único `cdn1.megaleiloes.com.br/{batches|auctions|bank_icons}`
  - Auditório em subdomínio dedicado `auditorio.megaleiloes.com.br`
- **CDN/Hosting**: `server: cloudflare`. Sem JS challenge no acesso
  normal. CDN próprio para mídia (`cdn1.`), separado do app principal.
- **Idiomas/i18n**: pt-BR fixo. Datas em `DD/MM/YYYY às HH:MM`,
  valores em `R$ NN.NNN,NN`.
- **robots.txt** (`https://www.megaleiloes.com.br/robots.txt`):
  ```
  User-agent: *
  Allow: /
  Disallow: /login
  Sitemap: https://www.megaleiloes.com.br/sitemap/sitemap_index.xml
  ```
  Permissivo para `/imoveis`, `/leiloes-realizados`, detail pages e
  `cdn1.megaleiloes.com.br/{batches,auctions}/`. Apenas `/login`
  bloqueado. **Sitemap apontado retorna 404** (probe confirmado);
  inutilizável como seed alternativo. Discovery deve sair de
  `/imoveis` (categoria-específico) ou `/leiloes-realizados` (auctions).
- **Single-tenant**: todos os 2 sites apontam para o mesmo
  domínio raiz; não há subdomínios por leiloeiro. Filial MS
  é apenas uma rota geográfica `/ms` que filtra por UF.

**Conclusão**: `requires_playwright = False`. Estática completa.

## Listing ativa

URL canônica: `/imoveis` (categoria pai). Variantes por subcategoria:
`/imoveis/apartamentos`, `/imoveis/casas`, `/imoveis/terrenos-e-lotes`,
`/imoveis/imoveis-comerciais`, `/imoveis/imoveis-rurais`,
`/imoveis/galpoes--industriais`, `/imoveis/glebas`, `/imoveis/hospitais`,
`/imoveis/hoteis`, `/imoveis/resorts`, `/imoveis/vagas-de-garagem`,
`/imoveis/deposito-de-garagem`, `/imoveis/casa-em-terreno-para-incorporacoes`,
`/imoveis/terrenos-para-incorporacao`, `/imoveis/outros`.

Filtros geográficos opcionais: `/imoveis/{categoria}/{uf}` e
`/imoveis/{categoria}/{uf}/{municipio}`. Aceita também rota raiz
`/{uf}/{municipio}` para todas as categorias.

Card selector: `div.card.open` (lots ativos). Estrutura:

- `a.card-image.lazyload[href]` → URL canônica do lote.
- `a.card-title` → título.
- `div.card-status` → badge de status (`Aberto para lances`, `Em breve`,
  `Aberto para propostas` em `/lotes-abertos`).
- `div.card-instance` > `div.card-instances` → praças (1 a 3).
- `div.instance.passed|.active|.future` → cada praça com:
  - `span.card-first-instance-date` ou `card-second-instance-date`
    (data + hora em `DD/MM/YYYY às HH:MM`).
  - `span.card-instance-value` → Lance mínimo daquela praça.
- `div.card-bank` → comitente (banco/empresa, opcional).
- `div.card-batch-number` → "Lote N" (badge `label-primary`).
- `div.card-locality` → "Cidade - UF".

**Filtros server-side observados**: `?categoria=`, `?ordenacao=`,
`?busca=`, `?vendedor=`. `?status=` **não** existe — filtro de
status é por path (`/lotes-abertos`, `/lotes-em-breve`,
`/leiloes-realizados`).

Paginação: `?pagina=N` (querystring). 24 cards/página em `/imoveis`.

## Listing encerrada

**`listing_closed != null` — provider EXPÕE encerrados via
`/leiloes-realizados`.** Estrutura em dois níveis:

1. **Nível 1 — leilões finalizados**: `/leiloes-realizados` lista
   *leilões* (não lotes). Cada card é `div.card.card-auction.finalized`
   com link `/leiloes-realizados/ML{auction_id}`. Mostra:
   - Título do leilão (frequentemente "Banco X: Imóveis [...]
     do dia DD/MM/YYYY").
   - `div.card-count` → N de lotes.
   - `div.card-views-bids` → views (`fa-eye`) e total de bids do
     leilão (`fa-legal`) — útil para priorização.
   - `div.card-status` = "Finalizado".
   - Início + Término do leilão (campo `instance.passed`).
   Paginação `?pagina=N`.

2. **Nível 2 — lotes do leilão encerrado**:
   `/leiloes-realizados/ML{auction_id}` mostra cada lote do leilão.
   Os cards têm a mesma estrutura de `/imoveis` mas:
   - `card-status` = "Finalizado".
   - URL do detalhe é prefixada por `/leiloes-realizados/`:
     `/leiloes-realizados/imoveis/{cat}/{uf}/{mun}/{slug}-{X{lot_id}}`.
   - Cada card mostra `fa-legal N` = quantidade de lances no lote
     (filtrar por > 0 para encontrar arrematados ricos em dados).
   - `div.card-instance-value` = lance inicial (igual ao detalhe).
   Mesmo paginador `?pagina=N`.

3. **Detalhe do lote encerrado**: idêntico ao detalhe ativo, com
   diferenças:
   - `<div class="message-sold">ARREMATADO</div>` quando vendido
     (também `SEM LICITANTES` quando 2ª praça falhou — não testado
     em piloto).
   - `<div id="tab-bids">` populado com `<table>` paginada em
     `?pagina-lances=N` (5 bids/pg).
   - `<div class="last-bid">` em `summary-info` traz "Último Lance"
     (= preço de arremate).

> Decisão de design: para o piloto usei o **Nível 2** como
> `listing_closed.url_pattern` (template parametrizado por
> `auction_id`). O Nível 1 é o ponto de entrada do crawl, mas
> não é uma listagem de *lotes* — listagens-de-leilões precisam
> ser expandidas, e isso é trabalho do spider (não do contrato
> declarativo). O `card_selector` de Nível 2 é o que extrai
> lots. Documento ambos os níveis aqui, no recon.

> **Caso paralelo**: SOLEON e leilao_pro foram opostos —
> SOLEON expõe encerrados (single-tenant SC), leilao_pro **não**.
> mega_leiloes expõe encerrados via dois níveis (lista de leilões
> → lotes), abrindo histórico de lances (8 neste piloto, todos com
> bidder mascarado pelo próprio provider).

## Pilot lot escolhido

URL: `https://www.megaleiloes.com.br/leiloes-realizados/imoveis/casas/ms/campo-grande/casa-91-m2-nucleo-habitacional-universitarias-campo-grande-ms-x122302`

Leilão pai: **ML33575** ("Banco Itaú: Imóveis Remanescentes do
dia 23/04/2026", Extrajudicial, comitente Itaú, 143 lotes total).

**Motivo da escolha**: dos lotes scanned em `/leiloes-realizados/ML33575`
(página 1, ~24 cards), apenas **alguns lots tinham bids > 0**. O
lot X122302 era o de maior volume de bids (8) e tem um histórico
público completo, com timestamps minuto-a-minuto durante o leilão
(22/04 14:12 → 23/04 15:00, 8 incrementos de R$ 5.000 cada). Outros
candidatos (X122324 com 6 bids, X122319 com 2 bids) tinham menos
densidade de dados. Lots com 0 bids retornam apenas "SEM LICITANTES"
no detalhe — pilot menos informativo.

Detalhes:

- **Lote 2** (badge "Lote 2"; ML33575 tem 143 lotes total).
- **Título**: Casa 91 m² - Núcleo Habitacional Universitárias -
  Campo Grande - MS.
- **Tipo**: casa (residencial, ocupada).
- **Endereço bruto** (extraído de `div#tab-description div.content`):
  "Avenida Gomes Carneiro, nº 37 - Casa do tipo MS.B.2.39. Núcleo
  Habitacional Universitárias, Bairro Alves Pereria, Campo Grande/MS."
  (Nota: a descrição original tem typo "PERERIA" — mantido bruto;
  Fase 2 normaliza.)
- **Áreas**: construída 39,93m² (cadastro municipal menciona 91,80m²
  — divergência conhecida); terreno 200,00m². Matrícula 72.018
  do 2º CRI Campo Grande.
- **AVALIAÇÃO**: `R$ 0,00 (Nao informado)` — provider exibe valor
  zero quando comitente AF (Itaú/Bradesco/Santander) não publica
  avaliação. `market_value_brl: null` documentado em parser_notes.
- **Lance Inicial** (= minimum_bid_brl): R$ 129.700,00 (também
  reiterado na descrição "Lance mínimo R$ 129.700,00").
- **Último Lance** (preço de arremate): R$ 164.700,00 (último bid
  da tabela, em 23/04/2026 15:00:00 BRT).
- **1 round** (Extrajudicial AF Lei 9.514, single-instance — só
  "Data" 23/04/2026 15:01, sem 2ª praça).
- **Bids exposed**: 8 lances completos via tabela paginada
  (5/pg → 2 páginas). Todos com `bidder_raw` já mascarado pelo
  próprio provider em formato `{3chars}*/*/*/*/*` —
  pseudonimização nativa do provider, não foi necessário redigir.
- **Imagens**: 2 fotos do bem (`/batches/122302/{hash}_{670x380|1024x768}.jpg`).
  Mesmo hash (1cb4afac) — é a mesma foto em 2 resoluções. Bancos AF
  costumam publicar mídia escassa para remanescentes.
- **Documentos**: 1 edital ML33575 + 1 matrícula X122302
  (ambos em `cdn1.megaleiloes.com.br/{auctions|batches}/.../*.pdf`).
- **`auction_status: "arrematado"`**. Confirmado por
  `<div class="message-sold">ARREMATADO</div>` no card-instance-info
  e `Último Lance R$ 164.700,00` ≠ vazio.

| Campo                    | Valor (resumido)                                    |
|--------------------------|-----------------------------------------------------|
| title                    | "Casa 91 m² - Núcleo Habitacional Universitárias - Campo Grande - MS" |
| description              | 1.115 chars                                         |
| property_type            | `casa`                                              |
| address.raw_text         | "Avenida Gomes Carneiro, nº 37, Núcleo Habitacional Universitárias [...] Campo Grande/MS" |
| address.uf               | `MS`                                                |
| address.municipality_name| `Campo Grande`                                      |
| address.cep              | null (descrição não inclui CEP)                     |
| area_sqm                 | "39.93"                                             |
| total_area_sqm           | "200.00"                                            |
| market_value_brl         | null (provider exibe R$ 0,00 / Não informado)       |
| rounds[1].minimum_bid    | "129700.00"                                         |
| rounds[1].scheduled_at   | 2026-04-23T15:01:00-03:00                           |
| auction_status           | `arrematado` (Último Lance R$ 164.700)              |
| bids[]                   | 8 (R$ 129.700 → R$ 164.700, todos bidder mascarado) |
| images                   | 2 fotos (mesma imagem em 2 resoluções)              |
| documents                | 2 (edital + matrícula)                              |

## XHRs descobertas

Não usei `xhr-first-recon` — site é estático e listing/detail/bids
todos vêm no HTML inicial. Mapeamento auxiliar para Fase 3:

- **`auditorio.megaleiloes.com.br/auditorio/{auction_id}/{lot_id}/batch`**:
  subdomain do auditório virtual (real-time bidding em leilão ao vivo).
  Requer auth para participação. **Fora do escopo** (PLANOMESTRE:
  leitura apenas; Fase 3 pode considerar SSE/WS para tracking, mas
  não para histórico).
- **`/sitemap/sitemap_index.xml`**: 404 (anunciado em robots.txt
  mas não publicado). Discovery via `/leiloes-realizados`
  paginado é a fonte canônica.

## Gotchas

1. **Single-tenant centralizado, não multi-site**: ambos os 2 sites
   no provider apontam para `megaleiloes.com.br` raiz (não
   subdomínios). A filial MS é apenas a rota `/ms`. Selectors são
   universais para o domínio.

2. **Avaliação `R$ 0,00` em leilões bancários AF**: Itaú, Bradesco
   e Santander (e provavelmente outros) NÃO informam avaliação no
   site Mega Leilões — o campo aparece como "R$ 0,00 (Nao informado)".
   Não é bug nem ausência de extração: o provider explicitamente
   sinaliza "não informado". `market_value_brl: null` é o correto;
   evitar tentar parsear "0" como valor real. Em leilões judiciais
   ou comitentes não-bancários, avaliação geralmente é preenchida.

3. **Bidder names já mascarados nativamente**: o provider exibe
   bidders no formato `{3chars}*/*/*/*/*` (ex.: `juc*/*/*/*/*`,
   `aba*/*/*/*/*`, `jci*/*/*/*/*`). Pseudonimização é responsabilidade
   do site, NÃO precisamos redigir adicional. PLANOMESTRE §4 fica
   pleno: a string já é não-identificável. Anote em parser_notes
   que NÃO houve redação.

4. **Dois níveis de "encerrado"**: `/leiloes-realizados` lista
   *leilões* (ML{id}), `/leiloes-realizados/ML{id}` lista *lotes*.
   O card_selector de listing_closed só faz sentido no Nível 2
   (lotes). Spider deve crawlear N1 → expandir N2 → entrar em
   detail.

5. **Dois paginadores distintos no mesmo path**:
   `?pagina=N` para listing de lotes ou leilões;
   `?pagina-lances=N` para tabela de bids dentro do detalhe.
   Querystring distinta evita colisão. 24 lots/pg em listing,
   5 bids/pg em tab-bids.

6. **PJAX nas tabelas**: `<div id="pjax-batch-bids"
   data-pjax-container="">` — o site usa pjax para trocar páginas
   da tabela de bids sem reload. Mas a request inicial e a paginada
   ambas retornam HTML completo (não fragmento). Spider crawlea
   normal — pjax é transparente.

7. **CDN próprio vs binários**: `cdn1.megaleiloes.com.br/batches/`
   serve fotos do bem; `cdn1.megaleiloes.com.br/auctions/` serve
   editais; `cdn1.megaleiloes.com.br/bank_icons/` serve logos.
   `bank_icons` precisa ser filtrado de `images[]` (não é foto do
   imóvel). Selector explícito `[src*='/batches/']` resolve.

8. **Fotos escassas em leilões bancários**: lots de bancos AF
   (Itaú/Bradesco/Santander) costumam ter 1-2 fotos só (mesma imagem
   em múltiplas resoluções). Lots judiciais podem ter 5-15 fotos.
   Não invente — capture o que estiver disponível.

9. **PII**: bidders já mascarados pelo provider (não-redact);
   descrição menciona apenas matrícula 72.018, 2º CRI Campo Grande,
   código interno do banco (921600). Sem CPF, sem nome PF de pessoas
   físicas. Sem redação aplicada.

10. **`/lotes-abertos` ≠ `/imoveis`**: `/lotes-abertos` filtra
    lotes em modalidade "Aberto para propostas" (lances livres ANTES
    do leilão começar — modalidade Mega Leilões específica). Não é
    a categoria imóveis. Para piloto de imóveis ATIVO, usar
    `/imoveis`.

11. **`status_raw` em rounds**: padronizei como string descritiva
    com início + data + outcome ("Finalizado — Início ... Data ...
    ARREMATADO em ... por R$ ..."). `validate.py` aceita; em Fase 2
    parser separa em campos canônicos.

## Decisões e limitações

- **`requires_playwright = False`**: HTML estático; bids inline.
- **`platform_hint = "mega_leiloes"`**: provider proprietário Yii2/PHP.
  Não há outras instâncias dessa stack catalogadas (single-provider).
- **`auctioneer_slug = "mega-leiloes"`**: representa o provider
  inteiro. Os 2 leiloeiros físicos (Fernando Pereira / Milena Adri)
  operam sob o mesmo CNPJ corporativo da Mega Leilões; site não
  diferencia leiloeiros por slug.
- **`source_listing_url`**: usei a URL do leilão pai
  (`/leiloes-realizados/ML33575`), não `/leiloes-realizados` raiz —
  é a listagem que efetivamente contém o lote piloto.
- **`listing_closed.url_pattern`** parametrizado por `auction_id`
  porque a listagem de lots está sempre dentro de um leilão
  específico (ML{N}).
- **`market_value_brl = null`**: limitação do provider para AF
  bancários (= "R$ 0,00 (Nao informado)"). Não é falha extração.
- **`bids` capturado integralmente**: 8 lances, paginação completa
  (2 páginas de 5/pg, total = 8 = bids-count badge).
- **PII zero redação**: provider já mascara bidders; descrição limpa.
- **Rate limit 1.5s** mantido em todos os fetches: home, robots,
  /imoveis, /leiloes-realizados, ML33575 lista, lot detail X122302
  página 1+2 de bids, probes 404 (`/lotes-encerrados`,
  `/imoveis-encerrados`, `/encerrados`, `/realizados`,
  `/busca-personalizada`, `/sitemap/sitemap_index.xml`,
  `?status=encerrado`). ≈12 requests, ~18s de delay.
- **Não baixei nenhum PDF nem imagem** (regra dura). URLs como
  referência declarativa em `documents[]` e `images[]`.

## Status do validador

Aguardando hook PostToolUse para rodar `validator/validate.py`.
Fill-rate alvo: ≈92%. SOFT esperados: `address.cep` (descrição
não publica CEP do bem), `market_value_brl` (provider exibe
"Não informado" para AF bancários).
