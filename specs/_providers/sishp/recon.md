# sishp

Recon arquitetural do **provider `sishp`** — plataforma PHP server-side
render identificada pelo prefixo de URL `/sishp/` em assets estáticos
(fotos, anexos, logomarcas). 6 leiloeiros catalogados em
`data/intermediate/site_analysis.csv` apontam para 3 tenants distintos
desta plataforma.

Tenant amostrado para o piloto: **`sfrazao.com.br`** (SFrazão Leiloeiros
Oficiais — Antônio Carlos Celso Santos Frazão e Victor Alberto Severino
Frazão, MT/SP). Foi o único dos 3 tenants do `_input.json` com
encerrados ricos publicados no índice (125 leilões encerrados na home,
~50% sendo imóveis).

Representativo do `_input.json` original era `lancenoleilao.com.br`
(Carla Sobreira Umino, SP). Mantido como spot-check arquitetural —
estrutura HTML idêntica, mas o tenant tem ~5× menos volume e o cache
estático mostrava poucos encerrados de imóveis.

## Tech stack & rendering

`site_analysis.csv` (linhas amostradas):

| tenant | rendering | tech_stack | tech_signals | static_useful_links |
|---|---|---|---|---|
| `sfrazao.com.br` | static | jQuery; Bootstrap | jquery \| bootstrap \| server:cloudflare | 3 |
| `lancenoleilao.com.br` | dynamic | jQuery; Bootstrap | jquery \| bootstrap \| server:cloudflare | 133 |
| `lancetotal.com.br` | static | jQuery; Bootstrap | jquery \| bootstrap \| server:cloudflare | 55 |

A discrepância de `rendering` entre tenants é falso-positivo do classificador:
**os três rodam o mesmo template PHP** (sinais canônicos abaixo). O diff
de useful_links cai na heurística de threshold do `site_analyzer`, não
em diferença real de rendering. Confirmado fetch direto: todos os 3
tenants entregam HTML completo via `httpx`, sem necessidade de
Playwright.

Sinais canônicos de plataforma (presentes nos 3 tenants):

- **Caminho `/sishp/...`** em assets estáticos:
  - `/sishp/leilao/{leilao_id}/fotos/{lote_id}_NN.{jpg|jpeg|png}` — fotos do lote
  - `/sishp/leilao/{leilao_id}/fotos/snapshot.jpg` — capa do leilão
  - `/sishp/leilao/{leilao_id}/anexos/{anexo_id}.pdf` — anexos do lote
  - `/sishp/arquivoAnexo/{anexo_id}.pdf` — edital do leilão
  - `/sishp/arquivoLogomarca/{NN}.{jpg|png}` — logo do comitente
  - `/sishp/publicidade/{NN}.{jpg|jpg}` — banners rotativos

- **Endpoints PHP padronizados** (todos os 3 tenants):
  - `index.php` / `/` — home com cards de leilões
  - `leilao.php?idLeilao={N}` — página de leilão (lista de lotes)
  - `lote.php?idLote={N}` — detalhe do lote
  - `pesquisa.php` — busca por bens **ATIVOS** apenas
  - `leilaoAnexos.php?idLeilao={N}&action=0` — modal iframe com edital
  - `loteAnexos.php?idLote={N}` — modal iframe com anexos do lote
  - `leilaoHabilitacao.php`, `leilaoImpressao.php`, `leilaoTransmissao.php`,
    `auditorio2.php`, `cadastreSe.php`, `efetuarLogin()` — fluxos auth
  - `processoNewsletter.php` — POST newsletter
  - `cdn-cgi/scripts/.../email-decode.min.js` — Cloudflare email obfuscation

- **Funções JS canônicas** inline:
  - `goTo('leilao.php?idLeilao=N')` — onClick handler de cards de leilão
  - `goToUrl('https://...')` — onClick handler de cards de lote (alguns
    leilões integram com PGFN: `https://comprei.pgfn.gov.br/anuncio/detalhe/N`)
  - `carregarAnexos(N)` — abre modal de anexos
  - `anexoCarregar('./sishp/...')` — carrega PDF dentro do iframe modal
  - `postToWindow('auditorio2.php', 'Auditorio', '', ['idLeilao'], ['N'])` — abre auditório

- **Stack inferida**: PHP procedural (extensão `.php` em todas as rotas),
  jQuery 3.x + Bootstrap 4 + FontAwesome + Slick Carousel + Fancybox,
  Cloudflare CDN+email-protection, Google Tag Manager + Facebook Pixel.
  Nome `sishp` = "Sistema HP" (provável "Hasta Pública" — nome do
  framework PHP do operador da plataforma; sigla aparece somente em
  paths de asset).

- **CSS classes específicas** (para badge → status canônico, ver mapa
  abaixo):
  - `back-1` (vermelho-escuro / vinho)  → "Vendido" (= arrematado)
  - `back-11` (cinza/claro)              → "Sem licitantes" (= encerrado)
  - `back-16` (azul)                     → "Em andamento" / "Saiba mais" (= ativo)
  - `back-3` (cinza médio)               → fundo do header do lote (não é badge)

- **robots.txt**: idêntico nos 3 tenants — apenas o boilerplate
  Cloudflare de "content signals" (search/ai-input/ai-train), **sem
  Disallow nem Allow**. Recon livre.

**Conclusão**: `requires_playwright = False`. Toda Fase 1 e Fase 2
podem rodar com `httpx` + `BeautifulSoup` (ou Scrapy puro).

## Listing ativa

URL canônica por tenant: **`/`** (home). A home é uma listagem de
**LEILÕES** (não de lotes individuais): cada card aponta para
`leilao.php?idLeilao=N`. Em sfrazao, a home retornou **135 leilões**
distintos numa única página (sem paginação). lancenoleilao retornou
~25, lancetotal ~10.

Card selector: `div.card.card-1` — contém:

- `onClick="goTo('leilao.php?idLeilao={N}')"` — ID do leilão (anchor canônico).
- `<img src="./sishp/leilao/{N}/fotos/snapshot.jpg">` — capa.
- `<img src="sishp/arquivoLogomarca/{NN}.jpg">` — logo do comitente.
- `<p class="card-title card-title-2">Id.: {N}</p>` — ID humano.
- `<p class="card-text small card-address-2">{TÍTULO_DO_LEILÃO}</p>` —
  descrição curta. Aqui aparece o filtro semântico para imóveis
  ("CASA", "APARTAMENTO", "TERRENO", "IMÓVEIS", "FAZENDA").
- `<li class="card-dates">{N} IMÓVEIS</li>` ou data — contagem de lotes ou data.
- `<a class="btn back-N">{TEXTO}</a>` — botão de status:
  - `back-16` "Saiba mais" → ativo.
  - `back-1` "Encerrado" → encerrado.
  - (não emite Vendido/Arrematado no nível de leilão — só no lote.)

Paginação: **`kind: none`**. A home cabe em 1 página em todos os 3
tenants amostrados. Não há `<nav class="pagination">` nem rota
`?page=N` aceita pelo backend.

**`pesquisa.php`** existe mas filtra **apenas ativos** (texto literal
no formulário: "EFETUE UMA BUSCA NOS BENS ATIVOS"). Útil para
discovery alternativo de bens individuais via classificacao/uf/cidade,
mas redundante para o piloto.

## Listing encerrada

**Não há rota dedicada** (`/encerrados.php`, `/leilaoEncerrados.php`,
`/realizados.php`, `/anteriores.php`, `/historico.php`,
`/arrematados.php` — todas 404 em sfrazao). O backend também não
implementa filtro de status server-side (`?status=encerrado` é
ignorado).

**Mas os encerrados ESTÃO publicamente visíveis** — interleaved na
home com os ativos. Em sfrazao, dos 135 cards de leilão na home:
- 1 ativo (`Saiba mais` no botão)
- 125 encerrados (`Encerrado` no botão)
- 9 sem badge claro (provavelmente em pré-leilão / "A ser definida")

A heurística para classificar é o texto do botão no `.card-footer`:
`<span>Encerrado</span>` em encerrados, `<span>Saiba mais</span>` em
ativos.

`listing_closed.url_pattern` = `/` (mesma URL da home).
`card_selector` usa XPath para filtrar pelo descendant text 'Encerrado'.

> **Caso paralelo**: SOLEON (`fabio-marlon-machado`) **expõe**
> `/leiloes/encerrados` paginado dedicado. `leilao_pro` não publica
> encerrados. SISHP fica no meio: publica todos (ativos + encerrados)
> na MESMA página, distinguíveis apenas por badge — ainda mais
> generoso que SOLEON em termos de descobrimento, porque a Fase 2
> nem precisa de uma rota separada para encontrar histórico.

**Implicação para o spider de produção**: 1 GET na home cobre
o universo de leilões (ativos + encerrados). O spider pega cada
`idLeilao=N` e itera sobre os `idLote=N` da página de leilão.

## Pilot lot escolhido

**URL**: `https://www.sfrazao.com.br/lote.php?idLote=2830`

Leilão pai: "TERRENO C/8.831,53M² AT, EM NAZARÉ PAULISTA /SP" (CÓDIGO 193),
modalidade On-line, Tipo Extrajudicial. Single-lote leilão (lot 001).

**Motivo da escolha**: o objetivo deste recon arquitetural é cobrir
**leilão encerrado COM lances**. Dos 4 lots inspecionados em
sfrazao em 4 leilões diferentes (113, 117, 158, 161, 7 → todos terminaram
sem licitantes), o único com bid público em real-estate single-lot foi
o lote 2830 do leilão 193:

- Avaliação: R$ 2.000.000,00
- Lance Mínimo: R$ 1.586.474,10 (= 79,3% da avaliação — provavelmente
  determinado pela Prefeitura, comitente)
- Encerramento: 21/03/2024 a partir das 11:00:00
- Maior Lance: R$ 1.586.474,10 (lance único = lance mínimo, à vista)
- Bidder: `id 9240` (pseudonimização nativa do provider — não há nome
  ou apelido público, somente ID interno)
- Data do bid: 12/03/2024 14:54:49 (BRT, -03:00)
- Status badge: "Vendido" (`back-1`)

Detalhes do imóvel:

- **Lote 001** (único do leilão; dropdown `Lote 001` mostra apenas 2830).
- **Título**: TERRENO C/8.831,53M² AT, EM NAZARÉ PAULISTA /SP.
- **Tipo**: terreno urbano (rua urbana, área da Prefeitura). Em
  processo de regularização — sem matrícula apresentada.
- **Endereço**: Rua Abrahão Farhat - Mascate - Nazaré Paulista/SP
  (extraído do anchor para Google Maps no bloco "Localização do bem").
- **Imagens**: 10 fotos (`/sishp/leilao/193/fotos/2830_{01..10}.jpg`).
- **Documentos**: 1 edital (`/sishp/arquivoAnexo/561.pdf`) + 1 anexo
  do lote (`/sishp/leilao/193/anexos/560.pdf`). Nenhum deles é
  matrícula (não foi apresentada — informado nas observações). Anexo
  do lote foi marcado como `kind: outro` por ausência de label
  específico.
- **Encumbrance**: imóvel em processo de regularização de área —
  registrado em `encumbrances_raw[]`.
- **`auction_status: "arrematado"`**. Badge "Vendido" (`back-1`).

| Campo                    | Valor (resumido)                                    |
|--------------------------|-----------------------------------------------------|
| title                    | "Lote 001 - TERRENO C/8.831,53M² AT, EM NAZARÉ PAULISTA /SP (CÓDIGO 193)" |
| description              | ~1.5 KB (perímetro completo + observações)          |
| property_type            | `terreno`                                           |
| address.raw_text         | "Rua Abrahão Farhat - Mascate - Nazaré Paulista/SP" |
| address.uf               | `SP`                                                |
| address.municipality_name| `Nazaré Paulista`                                   |
| address.cep              | null (não publicado)                                |
| total_area_sqm           | "8831.53"                                           |
| area_sqm                 | null (terreno bruto, sem área útil distinta)        |
| market_value_brl         | "2000000.00"                                        |
| rounds[1].minimum_bid    | "1586474.10"                                        |
| rounds[1].scheduled_at   | 2024-03-21T11:00:00-03:00                           |
| auction_status           | `arrematado` (Vendido)                              |
| bids[]                   | 1 (`id 9240`, R$ 1.586.474,10, 12/03/2024 14:54:49) |
| images                   | 10 fotos                                            |
| documents                | 2 (edital + anexo do lote)                          |
| encumbrances_raw         | 1 (regularização de área pendente)                  |

## XHRs descobertas

**Site não é SPA — não usei `xhr-first-recon`**. Toda data está
inline em HTML server-rendered. Os únicos XHRs do fluxo de visitante
são:

- `leilaoAnexos.php?idLeilao={N}&action=0` (modal iframe) — retorna
  HTML com `<a onClick="anexoCarregar('./sishp/arquivoAnexo/{anexo_id}.pdf')">`.
  Útil para o spider extrair os PDFs de edital programaticamente.
- `loteAnexos.php?idLote={N}` (modal iframe) — análogo, para anexos
  do lote.
- `auditorio2.php` (POST) — sala ao vivo do leilão; só ativa durante
  janela de pregão e exige login (gating server-side). Fora do escopo
  do recon. Mecanismo de bid em tempo real provavelmente AJAX longpoll
  ou WebSocket interno (não inspecionado — escopo Fase 3).

## Gotchas

1. **Multi-tenant uniforme, mas volumes muito diferentes**. 6 sites
   declarados em `_input.json` apontam para apenas 3 domínios distintos
   (`lancenoleilao`, `lancetotal`, `sfrazao`) — o input rotula
   leiloeiros, e múltiplos leiloeiros podem co-habitar o mesmo tenant
   (ex.: 3 leiloeiros sob `sfrazao.com.br`; 2 sob `lancetotal.com.br`).
   Selectors são portáveis entre tenants.

2. **`rendering=dynamic` em lancenoleilao é falso-positivo**. O HTML
   inicial já tem todos os cards. A discrepância no `site_analyzer`
   provavelmente vem de DOM transformations cosméticas pós-load (slick
   carousel, etc.). Não confunda com SPA.

3. **Bidder anônimo nativo (`id 9240`)** — diferente de SOLEON e
   leilao_pro (handles em claro). O provider já pseudonimiza no
   render. **Nada a redigir**: PLANOMESTRE §4 não exige redação de
   identificadores opacos. Cuidado se o spider de produção encontrar
   formato `Username (id N)` em algum tenant futuro — aí o handle
   precisa de avaliação caso-a-caso.

4. **Leilão "PGFN Comprei" delega externamente**. O leilão 262 da
   sfrazao tem cards onClick=goToUrl('https://comprei.pgfn.gov.br/...')
   — bens da Procuradoria-Geral da Fazenda Nacional listados via
   sfrazao mas com detalhe **fora do tenant**. O spider deve filtrar
   esses (ou tratá-los como referência cruzada). Detectável: ausência
   de `lote.php?idLote=` na página do leilão; presença de PGFN URLs.

5. **Nem todo encerrado tem bid**. 5/7 leilões probados terminaram
   "Sem licitantes" (badge `back-11`). O spider deve coletar todos
   indistintamente (estado terminal informativo) — diferente de
   leilao_pro onde o lot some do índice.

6. **Datas em formato misto**. Header do lote: `Abertura: 07/Mar/2024,
   10h00<br>Encerramento: 21/Mar/2024, 11h00`. Bloco "Encerramento,
   valores e lances": `21/03/2024 a partir das 11:00:00`. Bid timestamp:
   `12/03/2024 às 14:54:49`. Três formatos no MESMO documento — parser
   precisa normalizar todos para `datetime` tz-aware (BRT, -03:00).

7. **Nenhuma 1ª/2ª praça anunciada no card**. SISHP segue o modelo de
   leilão único online (Lei 21.981/1932 administrativo + Lei 11.441
   judicial conforme tipo). Praças formais aparecem (se aplicável) só
   no PDF do edital. Para o piloto, `rounds: [único]` é correto.

8. **Edital exige round-trip extra**. O botão "Edital do leilão"
   abre um iframe modal — a URL real do PDF só vem da página
   `leilaoAnexos.php?idLeilao=N&action=0`. Spider precisa de 1
   request adicional por leilão. URL do PDF não é previsível
   (`/sishp/arquivoAnexo/{anexo_id}.pdf` — anexo_id é sequencial
   global da plataforma, não derivável de leilao_id).

9. **Cloudflare email obfuscation**. Footer tem
   `<span class="__cf_email__" data-cfemail="...">[email&#160;protected]</span>`.
   Irrelevante para o item, mas confunde parsers ingênuos. Ignorar.

10. **`area_sqm` vs `total_area_sqm`**. Em terreno bruto sem benfeitoria
    (caso do piloto), só faz sentido `total_area_sqm`. Em casa/apartamento,
    o spider precisa parsear "AC" (área construída → `area_sqm` útil) vs
    "AT" (área total → `total_area_sqm`) do título — exemplo em outros
    cards da home: "CASA C/ 332M² AT E 159M² AC".

11. **Auditório (`auditorio2.php`)** é endpoint exclusivo de pregão
    ao vivo, requer login. Fora do escopo da Fase 1 (só leitura
    pública). Em Fase 3, monitor real-time provavelmente exige sessão
    válida — não-trivial.

12. **PII**: descrição, observações e endereço **não** trazem CPF
    nem nome PF identificável. Bidder é `id 9240` (opaco). O CPF do
    leiloeiro (`048.979.008-91`) aparece em campos de pagamento de
    OUTROS lots (e.g., lote 2628 em /pesquisa.php), em contexto de
    PJ/profissional — não redijo, mas o spider de produção deve
    incluir `048.979.008-91` na lista de blocklist de CPF de agentes
    públicos para evitar falsos positivos. Neste lote (2830), nada a
    redigir.

13. **`Lance Mínimo` ≠ `% da avaliação` padrão**. No lote 2830,
    R$ 1.586.474,10 / R$ 2.000.000,00 = 79,32%. Não é nem 100%
    (1ª praça típica) nem 50-60% (2ª praça típica). Provavelmente
    determinado pelo edital específico (Prefeitura de Nazaré
    Paulista). Spider não deve assumir % fixo entre `market_value`
    e `minimum_bid`.

## Decisões e limitações

- **`requires_playwright = False`**: HTML server-side completo. Nem
  no detalhe nem na listagem precisa Chromium.
- **`platform_hint = "sishp"`**: canônico. Caminho `/sishp/...` é a
  fingerprint mais robusta (presente em todos os 3 tenants amostrados,
  nunca observado em outras plataformas durante este recon).
- **`auctioneer_slug = "sfrazao-leiloeiros-oficiais"`** no piloto. O
  recon arquitetural cobre o **provider**, não o leiloeiro individual
  — por isso vivemos em `specs/_providers/sishp/`. O input apontava
  `carla-sobreira-umino` (lancenoleilao) como representante; o piloto
  efetivo é em sfrazao por motivo HARD (encerrado com bid de imóvel
  só foi encontrado lá no tempo de recon).
- **`listing_active.url_pattern = "/"`**: home é a listagem.
  `pesquisa.php` poderia ser alternativa para spider de produção
  (filtros UF/categoria), mas só cobre ATIVOS e adiciona complexidade.
- **`listing_closed.url_pattern = "/"`** (mesma URL): encerrados estão
  na home, distinguíveis pelo descendant text 'Encerrado'.
- **`bids` capturado**: 1 lance, com timestamp + valor + tipo. Bidder
  já vem opaco do provider — sem PII para redigir.
- **Rate limit 1.5s** mantido em todos os ~25 fetches do recon
  (~38s de delay efetivo).
- **Não baixei nenhum PDF nem imagem** (regra dura).
- **robots.txt**: apenas content-signals da Cloudflare, sem
  Disallow/Allow. Recon livre — todos os fetches feitos sem violação.

## Status do validador

Aguardando hook PostToolUse para rodar `validator/validate.py`.
Fill-rate alvo: ≈92% (24/26 — pendentes esperados: `address.cep`,
`address.complement`, `address.number`, `area_sqm`).
