# bomvalor

Recon arquitetural do provider **Mercado Bomvalor**
(`mercado.bomvalor.com.br`) — plataforma multi-tenant brasileira que
hospeda a totalidade do ciclo de leilão (listagem, detalhe, ofertas)
de pelo menos **10 leiloeiros INNLEI** ligados ao grupo (APA & BRF /
Adriana Pires Amancio em MG; multleiloes/Fernando Costa; Eder Jordan
de Souza ("ReiDos"); Francisco David Batista de Souza; Dênis de
Oliveira Fernandes; Sebastião Felix da Costa Neto / costanetoleiloeiro;
e mais 4 listados em `_input.json`).

Recon foi conduzido com APA & BRF (`apabrfleiloes.com.br`) como
tenant representativo, mas a estrutura é idêntica para todo tenant —
basta trocar `{tenant_slug}` no path.

## Tech stack & rendering

| Indicador                          | Valor                                                |
|------------------------------------|------------------------------------------------------|
| `tech_stack` (site_analysis)       | jQuery; Bootstrap                                    |
| `tech_signals`                     | jquery, bootstrap, server:cloudflare                 |
| `rendering`                        | hybrid (CSV) / **estático na prática para imóveis** |
| `requires_js_for_listings`         | False                                                |
| `static_useful_links` (representante) | 27                                                |
| Inline state (lotes ativos)        | `<script> sharedData = { lote: {...}, ... } </script>` (JS-literal, brace-balance + `json.loads` no sub-bloco) |
| Inline state (lotes encerrados)    | `sharedData` ausente — extração 100% HTML           |
| Web framework                      | Vue + jQuery + Bootstrap (Tailwind utility classes em fragmentos novos como `bv-praca`) |
| CDN principal                      | `d3r4ngrkezrhn6.cloudfront.net/public/<rede>/...`   |
| CDN documentos                     | `vlance-cdn.com.br/public/<rede>/anexo/{ts}.pdf`    |
| Cartório de registro de evento     | `cartoriocomprova.bomvalor.com.br/evento/{sid}.e`   |
| Robots                             | `mercado.bomvalor.com.br/robots.txt`: `Allow: /` (Disallow vazio). Tenant facade (`apabrfleiloes.com.br/robots.txt`) só publica content-signal Cloudflare; sem disallows. |
| Header server                      | Cloudflare; cookies WCL.Atf + XSRF-TOKEN (não exigidos para leitura pública) |

**Conclusão**: HTML 100% server-side suficiente para Fase 1. Confirmei
com `httpx + UA="TodoLeilaoBot/1.0"` em todas as rotas observadas.
**`requires_playwright = False`**. O endpoint AJAX `ver-mais-leiloes`
existe e seria útil para paginação infinita, mas o piloto se baseia
em proveniência HTML completa, não dependendo dele.

## Listing ativa

URL canônica do tenant: `https://mercado.bomvalor.com.br/{tenant}/`
(p. ex. `https://mercado.bomvalor.com.br/apabrfleiloes/`).

A home renderiza apenas as primeiras ~10 entradas como cards
(11 `a[href*='/imoveis/']` no recon do APA; "Total de 500 eventos em
andamento" reportado no header). Para listar **todos os imóveis
ativos** de um tenant, a URL canônica passa a ser:

```
https://mercado.bomvalor.com.br/{tenant}/busca/segmento/imoveis
```

Que retorna 30 cards no HTML inicial (`/imoveis/` anchors únicas).
Filtros adicionais por estado/segmento são paths encadeados:
`busca/segmento/imoveis/estado/MG/redeSegmento/bomvalorjudicial`,
`busca/segmento/imoveis/categoria/casa`, etc.

**Selector**: `a[href*='/imoveis/']` (CSS estável). Cada anchor já
identifica a categoria (`/imoveis/{categoria_slug}/{lot_slug}-{lot_id}`,
ex. `apartamento`, `casa`, `terreno`, `galpao-industrial`,
`hotel-complexo-hoteleiro`, `lote-residencial`, etc.). O `lot_id` é
sempre o sufixo numérico após o último `-`.

**Paginação**: querystring AJAX. JS de home faz:

```js
fetch(`${path}ver-mais-leiloes?perPage=${perPage}&page=${page}&eventos=`,
      { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
```

Spider de produção pode bater diretamente em
`https://mercado.bomvalor.com.br/{tenant}/ver-mais-leiloes?perPage=100&page=N&eventos=`
até resposta vazia (não testei reproduzir o XHR neste recon — não foi
necessário pro piloto, e a `/busca/segmento/imoveis` já retorna 30
cards num único request).

## Listing encerrada

URL canônica: `https://mercado.bomvalor.com.br/{tenant}/?eventos=encerrados`.

O JS de home (`build/assets/home-001ef8ee.js`) checa
`URLSearchParams(...).has("eventos")` e altera o filtro server-side. Confirmado:
o request com `?eventos=encerrados` retorna 14 imóveis encerrados
(distintos das ativas) com pílula visual "Encerrado" / "Suspenso" /
"Praça Encerrada".

> Tentativa alternativa: `/busca/segmento/imoveis/status/encerrado` é
> aceita pelo servidor mas **ignora o filtro** (responde igual ao
> `/busca/segmento/imoveis` puro — 30 ativas). Outra tentativa,
> `/busca/encerrado/segmento/imoveis`, retorna 7 lotes mas estes ainda
> exibem pílulas "Em Pregão" — comportamento inconsistente. **A rota
> oficial é `/?eventos=encerrados`**.

Selector idêntico ao listing_active: `a[href*='/imoveis/']`. Mesma
paginação AJAX (`ver-mais-leiloes?...&eventos=encerrados`).

## Pilot lot escolhido

URL: `http://mercado.bomvalor.com.br/apabrfleiloes/imoveis/apartamento/apartamento-75-m-em-belo-oriente-mg-116118`

(Mantive `http://` porque é o que aparece literal no HTML — `og:url`
content e share-links Facebook/Twitter/WhatsApp/LinkedIn. O HARD do
validador exige que `str(source_lot_url)` apareça **literalmente** em
`pilot_source.html`; com `https://` a proveniência quebraria. Não há
`<link rel="canonical">` na página deste provider.)

Evento ID 34428 (`Bomvalor Judicial`), Lote 1, **encerrado SEM
ARREMATAÇÃO**: 1ª praça (23/04/2026 13:30) "Não Vendido", 2ª praça
(07/05/2026 13:30) "Cancelado". Ambas com lance inicial R$ 180.000,00
(o "MAIOR OFERTA R$ 180.000,00" da 2ª praça é label genérico no DOM,
não houve lance real — confirma "Não Vendido" da 1ª).

| Campo                    | Fonte / Seletor                                                        | Valor (resumido)                            |
|--------------------------|------------------------------------------------------------------------|---------------------------------------------|
| title                    | `h1.titulo-lote`                                                       | "Apartamento 75 m² em Belo Oriente/MG"      |
| description              | `meta[property='og:description']` (limpa de HTML)                      | 1.0 KB                                      |
| property_type            | URL slug `/imoveis/apartamento/...`                                    | `apartamento`                               |
| area_sqm                 | regex `aproximadamente (\d+) m²` na descrição                          | 75.00                                       |
| address.raw_text         | `p.localizacao-leilao` + complemento "2º piso" + CEP 35195-000 (desc)  | "Rua Rio Grande do Norte, nº 411 – 2º piso, Centro, Belo Oriente/MG – CEP 35195-000" |
| address.street_name      | regex                                                                  | "Rua Rio Grande do Norte"                   |
| address.number           | regex                                                                  | "411"                                       |
| address.complement       | desc                                                                   | "2º piso"                                   |
| address.district         | `localizacao-leilao` ("..., Centro, ...")                              | "Centro"                                    |
| address.municipality_name | regex                                                                 | "Belo Oriente"                              |
| address.uf               | regex `/MG`                                                            | "MG"                                        |
| address.cep              | regex `CEP\s*([\d-]+)` na desc                                         | "35195-000"                                 |
| rounds[1].minimum_bid    | `div.bv-praca[data-nu-praca='1'] div.bv-vl-lance` (R$ 180.000,00)      | 180000.00                                   |
| rounds[1].scheduled_at   | `div.bv-praca[data-nu-praca='1']` (qui., 23 de abr. de 2026, 13:30)    | 2026-04-23T13:30:00-03:00                   |
| rounds[1].status_raw     | `div.bv-praca[data-nu-praca='1'] div.status-praca`                     | "Não Vendido"                               |
| rounds[2].minimum_bid    | idem 2ª praça                                                          | 180000.00                                   |
| rounds[2].scheduled_at   | qui., 07 de mai. de 2026, 13:30                                        | 2026-05-07T13:30:00-03:00                   |
| rounds[2].status_raw     | `div.bv-praca[data-nu-praca='2'] div.status-praca`                     | "Cancelado"                                 |
| auction_status           | derivado: 1ª "Não Vendido" + 2ª "Cancelado" → `encerrado`              | `encerrado`                                 |
| bids                     | `<div id='log-lances' class='d-none'>` placeholder, login-gated         | `[]`                                        |
| images                   | regex `cloudfront\.net/public/bomvalorjudicial/fotos/imoveis/.*\.jpg`  | 2 URLs (327x244)                            |
| documents                | `a[href*='vlance-cdn.com.br'][href$='.pdf']`                           | 1 doc (laudo: "Avaliação")                  |
| market_value_brl         | (null — não publicado em HTML; arquivo `Avaliação` está em PDF)        | null (SOFT)                                 |

### Lance histórico (closed-auction-bids skill)

**Não exposto publicamente.** O div `#log-lances` (que contém
`<table>` "Maior Oferta" + "Ofertas Superadas" + modal "Ver histórico
de ofertas" via `mostrarHistoricoDeLances()`) está com classe `d-none`
e **valores placeholder**:

```
<span class="apelido">X***</span>
<td class="data-hora">XX/XX/XXXX - XX:XX:XX</td>
<td class="valor-e-comissao">R$ XXX.XXX,XX + X%</td>
<h2 class="valor-lance">R$ XXX,XX</h2>
```

O conteúdo real é injetado client-side **somente para usuários
autenticados habilitados**. O modal `mostrarHistoricoDeLances()`
provavelmente faz request a um endpoint protegido. Para guest scrape
honesto: **`bids: []`** com `parser_notes` documentando.

Mesmo lotes "Vendido" (vi 2 ocorrências do termo na master encerrados,
mas sempre como banner promocional, nunca como pílula de status real)
não expõem histórico. Provider trata bid history como dado privado.

## Gotchas

1. **Multi-tenant via subpath, não subdomain**: tenants do Bomvalor
   ficam em `mercado.bomvalor.com.br/<slug>/...` (não em
   `<slug>.bomvalor.com.br`). O domínio público (apabrfleiloes.com.br)
   é fachada Cloudflare que linka para o mercado. Spider deve
   crawlear `mercado.bomvalor.com.br` direto e iterar `tenant_slug`
   conhecido — não há descoberta auto pelo subpath.

2. **`sharedData` aparece só em ATIVOS**: lotes em pregão carregam
   `<script>sharedData = { userId: null, loteId: ..., leilaoId: ...,
   lote: {...}, ... }</script>` com JSON-literal completo. **Lotes
   encerrados/cancelados perdem esse bloco** — tem que extrair via
   HTML estruturado (`bv-praca`, `localizacao-leilao`, og:description,
   etc.). Spider precisa duas estratégias: ATIVO usa `sharedData`
   direto; ENCERRADO usa fallback HTML.

3. **`sharedData` é JS-literal, não JSON puro**: chaves como `userId:`,
   `loteId:`, `lote:` não estão entre aspas. Não dá `json.loads` na
   string toda. Estratégia: localizar `lote: {`, fazer brace-balance
   (atento a `"` aspados e escapes) e parsear o sub-bloco — esse sim
   é JSON válido. Idem `leilao: {`, `judicial: {`, etc.

4. **Bids login-gated**: histórico de ofertas existe (Maior Oferta,
   Ofertas Superadas) mas é renderizado com placeholders `X***` /
   `XX:XX:XX` / `R$ XXX,XX` para guest. Scrape honesto = `bids: []` +
   nota em `parser_notes`. Tentar contornar exigiria criar conta /
   "Conta Comprova" — fora do escopo (não burlamos auth).

5. **CEP no og:description, não no HTML visual**: `localizacao-leilao`
   exibe só "Rua, Número, Bairro, Cidade/UF". CEP só aparece dentro
   do `og:description` (HTML-encoded em `&lt;p&gt;...CEP 35195-000&lt;/p&gt;`).
   Spider precisa parsear og:description (regex `CEP\s*([\d-]+)`)
   ou parsear desc visual completa (`.bv-descricao-completa`).

6. **`area_sqm` em prosa, não em campo estruturado**: a área (75 m²)
   só aparece como texto livre em `og:description`/descrição completa
   ("aproximadamente 75 m² de área construída (7,5 x 10 m)"). Não há
   `vl_areaconstruida` ou similar. Em ATIVOS, `sharedData.lote` também
   não traz área — está só na prosa.

7. **`market_value_brl` indisponível como número**: avaliação está em
   PDF anexo (`/anexo/{ts}.pdf` rotulado "Avaliação"). Provider não
   publica o valor numérico em campo estruturado. Para Fase 2, ler o
   PDF (OCR/text-extraction) seria a única via — fora do escopo aqui.
   `market_value_brl=null` é a leitura honesta.

8. **2 praças com mesmo lance inicial**: padrão de leilão
   judicial-extrajudicial. R$ 180.000 em ambas. A "MAIOR OFERTA
   R$ 180.000,00" da 2ª praça é só o **label do widget vazio**, NÃO
   um lance real (status da praça é "Cancelado" sem licitante). Não
   confundir com `bids[]`.

9. **3 hosts em jogo**: (a) `apabrfleiloes.com.br` (fachada, redireciona
   para o mercado quase imediatamente em todos os links de imóvel);
   (b) `mercado.bomvalor.com.br` (canônico, listagem+detalhe);
   (c) `vlance-cdn.com.br` (anexos PDF) e
   `d3r4ngrkezrhn6.cloudfront.net` (fotos+layout). UA respeitado em
   todos; nenhum exigiu cookies de sessão para GET público.

10. **URL canônica usa `http://`**: `og:url` content + todos os share
    links carregam `http://mercado.bomvalor.com.br/...` (não https).
    O servidor responde 200 em ambos os schemes mas o conteúdo
    embutido é http://. Para passar HARD provenance do validador
    (`source_lot_url` literal em pilot_source.html), mantive
    `http://` no `pilot_item.json`.

11. **Pílulas "Encerrado" no listing podem mascarar lots cancelados**:
    14 imóveis em `?eventos=encerrados`, mas apenas alguns são
    arrematados/sem-arrematação reais — outros estão "Suspensos" ou
    "Cancelados". Spider deve usar **`auction_status` derivado das
    praças no detalhe**, não da pílula da listagem (a pílula é
    agregada).

12. **PII**: lote piloto não tem CPF nem nome PF identificável.
    Comitente é institucional/judicial; leiloeira (Adriana Pires
    Amancio, JUCEMG) é agente público. Outros lotes do provider
    podem trazer "Executado:" + nome PF — Fase 2 deve aplicar
    pseudonimização ao copiar para `description`. Nada redigido
    neste pilot.

## Decisões e limitações

- **`platform_hint = "bomvalor"`**: canônico. Provider single-platform
  para todos os 10 tenants INNLEI listados.
- **`requires_playwright = False`**: HTML server-side suficiente.
- **`listing_active.url_pattern`**: `/busca/segmento/imoveis` (mais
  cards no primeiro request que a home pura).
- **`listing_closed.url_pattern`**: `/?eventos=encerrados`.
- **`bids = []` deliberado**: provider não expõe histórico para guest;
  alternativa seria criar conta autenticada (fora do escopo). Em Fase
  2, se a equipe optar por scrape autenticado, o seletor já está
  documentado em `selectors.yaml::detail.field_selectors.bids`.
- **`market_value_brl = null`**: SOFT warning aceito (avaliação só em
  PDF anexo).
- **`total_area_sqm = null`**: lote é apartamento → `area_sqm`
  (construída) cobre; total não publicado.
- **`encumbrances_raw = []`**: não há `vistoria.nm_onus` em lotes
  encerrados (esse campo aparece em `sharedData` de ATIVOS). Para
  detalhamento de ônus em lotes encerrados, parsear PDF Avaliação.
- **Rate limit ≥1.5s** mantido em todos os fetches (≥10 requests
  totais ao mercado.bomvalor.com.br + 3 ao tenant facade + 3 ao
  robots.txt + 1 home.js = ~25s de delay total).
- **Imagens só em 327x244**: o HTML da página encerrada referencia
  apenas a thumbnail. Lotes ativos (`sharedData.lote.fotos[]`) trazem
  URLs em resoluções maiores. Trade-off aceito: marquei `is_thumbnail:
  true` nas duas imagens deste piloto.
- **Cobertura do provider**: 10 tenants no `_input.json`. Spider
  parametrizado por `{tenant_slug}` deve funcionar em todos. Validação
  cross-tenant fica para Fase 2 (já mapeei a estrutura única).

## Status do validador

`validation.json::passed_hard = true` na **1ª tentativa**.
**1 SOFT warning**: `market_value_brl ausente` (justificado: provider
não publica avaliação como número em HTML; só PDF). Fill rate 21/25 =
84% (`total_area_sqm`, `market_value_brl`, `bids`, `encumbrances_raw`
em zero — todos justificados).
