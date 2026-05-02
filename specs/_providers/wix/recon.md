# wix (architectural recon — provider bucket)

## Tech stack & rendering

`Wix.com Website Builder` (Thunderbolt runtime, parastorage CDN, React DOM).
`tech_signals`: `generator=Wix.com Website Builder | data-reactroot/react-dom | bootstrap`.
Site_analysis: `rendering=static`, `requires_js_for_listings=False`,
`static_useful_links=17`, `dynamic_useful_links=17` (estavel — HTML
inicial ja carrega tudo o que existe). HTML servido por `siteassets.parastorage.com`
+ `static.parastorage.com`; conteudo do leiloeiro em `wix-usrfiles.com`.

robots.txt permite tudo exceto `*?lightbox=` (irrelevante aqui).
Sitemap (`/pages-sitemap.xml`) lista exatamente 5 URLs canonicas:
`/`, `/sumariodequalificacoes`, `/leiloesarealizar`, `/leiloesrealizados`,
`/contato`. Nao ha URLs por lote — Wix nao gera per-item routes para
o tipo de site usado por estes leiloeiros.

## Achado arquitetural — `wix` NAO e plataforma de leilao

`wix` no agrupador de providers e detector de **tech-stack** (Wix.com
Website Builder), nao plataforma especializada como SOLEON, leilao_br,
projud-ApiEngine, leilotech etc. Os 3 sites no bucket sao paginas de
marketing estatico construidas em Wix:

1. **`arquimedesleiloes.com.br`** (representativo) — Jose Arquimedes
   Camara, Montes Claros/MG. Pagina `/leiloesarealizar` traz texto
   manualmente escrito descrevendo leiloes presenciais antigos
   (2018-2019, "adiados") em saguao de forum. Sem URLs por lote, sem
   fotos por lote, sem edital online ("EDITAL E OUTRAS INFORMAÇÕES COM
   O LEILOEIRO OFICIAL"), sem historico de lances. Pagina
   `/leiloesrealizados` lista apenas categorias de clientes (TJMG, TRT,
   RFFSA, INFRAERO, IEF/Minascaixa, prefeituras) sem dados de lote.

2. **`leiloestaniaabreu.wixsite.com/leiloes/home`** — Wix subdomain
   gratuito (banner "This website was built on Wix"). Apenas contato
   + texto "VISITE NOSSA PAGINA DOS PROXIMOS LEILOES" sem link. Zero
   estrutura de lote.

3. **`dloficiais.com.br`** — Duarte Leiloes Oficiais (Joinville/SC).
   Pagina marketing Wix com botao "ACESSE NOSSA PLATAFORMA DE LEILOES"
   apontando para `https://www.duarteleiloes.com.br/?searchType=opened&
   preOrderBy=orderByFirstOpenedOffers&pageNumber=1&pageSize=30&orderBy
   =endDate:asc` — outro dominio, outro provider (provavel leilao_pro
   ou softgt; nao foi reconhecido aqui). O conteudo de leilao real fica
   em duarteleiloes.com.br, NAO no wix.

**Implicacao:** providers identificados apenas por tech-stack genérico
(Wix, Wordpress, Drupal puro) frequentemente nao tem paginas de lote.
Recomendacao para a Fase 2: re-classificar este bucket — sites Wix com
"plataforma externa" devem ser retesados via discovery (a fonte real
e o dominio externo, nao o Wix).

## Listing ativa

`/leiloesarealizar` (HTML 200, 460 KB, 100% server-rendered).
"Listagem" no sentido tradicional **nao existe**. A pagina e uma
sequencia de paragrafos/secoes textuais separadas por cabecalhos:

```
LEILOES JUDICIAIS NA COMARCA JANUARIA/MG
  PRIMEIRO LEILAO: 16/AGOSTO/2019 ... (texto livre)
  SEGUNDO LEILAO: 13/SETEMBRO/2019 ... (texto livre)
  IMOVEL RURAL: Fazenda Santo Antonio, ...
  SEMOVENTES - GADO BOVINO: ...

LEILAO JUDICIAL NA COMARCA DE JANAUBA/MG
  PRIMEIRO LEILAO: 04/outubro/2019 ...
  ...
  LOTE 01: 220 matrizes ... R$1.651,00 ........ 363.220,00
  LOTE 02: 120 novilhas  ... R$970,00 .......... 116.400,00
  TOTAL ............................................. 479.620,00

LEILAO JUDICIAL NA COMARCA DE MONTES CLAROS/MG
  PRIMEIRO LEILAO: adiado
  SEGUNDO LEILAO: adiado
  CASA RESIDENCIAL: Rua Santa Lucia n. 519, bairro Todos os Santos,
                    Montes Claros/MG. AVALIACAO: R$ 740.000,00.
```

Spider real, se for produzir items, precisa **parser heuristico
textual** (BeautifulSoup get_text + regex), nao selectors por card.
`card_selector` em `selectors.yaml` e best-effort sobre containers Wix
(`[data-testid='richTextElement']`, `wow-image`, `#PAGES_CONTAINER section`).

Pagination = `none`. A pagina e unica.

## Listing encerrada

**Nao existe publicacao estruturada de encerrados neste provider.**

`/leiloesrealizados` traz apenas:

```
Leiloes Realizados (amostragem)
JUDICIAIS: TJMG, TRT e outros;
ENTIDADES FEDERAIS: RFFSA, INFRAERO, AERONAUTICA ... e outros;
ENTIDADES ESTADUAIS: IEF/Instituto Estadual Florestas, Minascaixa,
  CASEMG e outros;
ENTIDADES MUNICIPAIS: Prefeitura de Bocaiuva, Carandai, Coracao de
  Jesus, Itaipe, Sao Joao do Paraiso e outras;
```

Apenas **categorias**, sem leilao individual, sem data, sem valor, sem
arrematante, sem lance. Mesmo padrao nos outros 2 sites Wix do bucket.
`listing_closed: null` em selectors.yaml com este motivo.

## Bids — historico de lances

**Provider nao expoe.** Wix nao tem mecanismo nativo de leilao online;
estes sites apenas anunciam leiloes presenciais que ocorrem em saguao
de forum ("LOCAL: saguao do Forum da Comarca de Januaria - TJMG").
Sem licitar online → sem `bids` para extrair, em qualquer site do bucket.

`bids: []` no pilot_item.json com `parser_notes` explicativo.

## Pilot lot escolhido

**Bloco "CASA RESIDENCIAL" em Montes Claros/MG** dentro de
`/leiloesarealizar`. Foi o item com dados mais completos:

- `title`: "Casa residencial colonial - Bairro Todos os Santos, Montes Claros/MG"
- `address.raw_text`: "Rua Santa Lucia, n. 519, esquina com rua Sao
  Marcos, bairro Todos os Santos (praca Wanderlei Fagundes), Montes
  Claros/MG"
- `area_sqm = 164` (construida), `total_area_sqm = 360` (terreno)
- `market_value_brl = 740000.00` (AVALIACAO)
- `rounds[0].minimum_bid_brl = 740000.00` (1a praca = preco igual ou
  superior ao da avaliacao, padrao judicial CPC art. 891)
- `rounds[1].minimum_bid_brl = null` (2a praca = melhor oferta sem
  preco vil; valor minimo nao publicado)
- `auction_status = suspenso` (ambos os leiloes "adiado")
- `property_type = casa`

`source_lot_url == source_listing_url`: a pagina e o lote (Wix nao
gera per-lot URL). Validador HARD passa porque a string aparece no
`pilot_source.html` (canonical = a propria URL).

## XHRs descobertas

Nenhuma. Site e 100% SSR — HTML estatico do Wix renderer entrega tudo.
`xhr-first-recon` nao se aplica. Capturado apenas `pilot_listing.html`
e `pilot_source.html` via httpx.

## Gotchas

1. **Wix em provider bucket = falso positivo.** Detectar tech-stack
   nao implica detectar plataforma de leilao. Re-classificar na Fase 2.
2. **Sites com "plataforma externa"** (`dloficiais.com.br` ->
   `duarteleiloes.com.br`): a Fase 2 deve seguir o link externo e
   re-rodar discovery sobre o dominio destino.
3. **Leiloes "adiados" desde 2019** sao norma neste site — pagina e
   atualizada raramente. Item piloto refleete o estado atual da pagina,
   mas nao e leilao "ativo" no sentido vivo do termo. `auction_status =
   suspenso` reflete isso.
4. **Avaliacao = lance minimo da 1a praca** (CPC art. 891 caput).
   Decisao tecnica para satisfazer HARD `1+ round com minimum_bid_brl`.
5. **Sem PII a redigir.** O texto da pagina menciona apenas o leiloeiro
   oficial (Jose Arquimedes Camara, agente publico — mantem) e
   localizacoes/foruns. Nenhum CPF, nenhum nome de devedor exposto.

## Decisoes e limitacoes

- `requires_playwright = False`: Wix entrega tudo em SSR. Spider real
  pode usar httpx + BeautifulSoup.
- `listing_closed = null`: provider nao expoe encerrados estruturados.
  Documentado.
- `bids = []`: provider nao expoe historico (leiloes sao presenciais
  em forum).
- `images = []`: pagina tem fotos decorativas (logo, banner equipe),
  nao fotos por lote. Filtrar em produccao com `wow-image[src]` e
  exclusao de path institucional ainda assim retornaria mistura ruim.
- `documents = []`: edital nao publicado online ("EDITAL E OUTRAS
  INFORMACOES COM O LEILOEIRO OFICIAL"). Limitacao de fonte.
- Fill rate: 80% (20/25 campos preenchidos). HARD: PASS.
- **Recomendacao orquestrador:** Para a Fase 2, esses 3 leiloeiros
  individuais (Jose Arquimedes, Tania Abreu, Tatiane Duarte) devem
  receber spiders **textuais** (parser de paragrafo) ou ser deferidos
  ate eles migrarem para uma plataforma estruturada. Spider generico
  "wix" so faz sentido se cobrir o subset que tem dados estruturados,
  o que aqui nao acontece.
