# softgt

Recon arquitetural do **provider `softgt`** (SoftGT Informática —
contato (41) 99936-7879 / (41) 99826-0000). 8 leiloeiros catalogados
no `_input.json`; 6 sites alcançáveis (`pbcastro`, `flexleiloes`,
`sfleiloes`, `lbleiloes`, `dalcanaleleiloes`, `luizleiloes`); todos
servem o mesmo template PHP + jQuery (sem framework SPA).

Tenant amostrado para o piloto: **`pbcastro.com.br`** (Plinio Barroso
de Castro Filho, PR — único tenant com volume operacional alto e
bid público ativo no momento da sondagem).

A escolha do `pbcastro` é deliberada: dos 6 tenants softgt acessíveis,
apenas pbcastro tem (a) listing ativo populado (34 leilões abertos em
2026-05-01); (b) um leilão encerrado paginado de fato (`/home-encerrado/`
com 156 leilões); (c) ao menos um lote ativo com **lance público
exposto** (`Mandy R$ 10.000,00`, 19/04/2026 14:56:14). flexleiloes
tem 46 leilões encerrados mas zero lotes com bid antes do início;
sfleiloes/lbleiloes/dalcanaleleiloes não publicam encerrados; luizleiloes
exige form de busca com data inicial/final pra listar encerrados.

## Tech stack & rendering

`site_analysis.csv` (linha 270, pbcastro) traz: `rendering=static`,
`tech_stack=jQuery`, `tech_signals=jquery | server:cloudflare`,
`static_useful_links=84`, `requires_js_for_listings=False`. Confirmado.

Sinais canônicos (em todos os 6 tenants softgt amostrados):

- `<meta name="author" content="SoftGT" />` no `<head>`.
- Rodapé `<a title="SoftGT (41) 99936-7879">SoftGT</a>` (variante
  com (41) 99826-0000 em flex/luiz).
- Stack: PHP server-side render + jQuery na frente
  (`/js/jquery.min.js`, `/js/menu.js`, `/js/messi.js`,
  `/js/leilao.js`, `/js/formularios/detalhe-lote.js`,
  `/js/gallery/fotorama.js`).
- Endpoints PHP descobertos no JS:
  - `POST /historico.php` body=`{bem, leilao}` — histórico de lances
    (até 3 últimos à vista + até 3 à prazo) + status do lote +
    contagem regressiva. **Esta é a API de bids.**
  - `POST /confirmar_lance.php` (auth) — envio de lance.
  - `POST /sair.php` (auth) — logout.
  - `POST /atualiza_lote.php` (existência inferida do JS) — usado
    pela navegação anterior/próximo lote.
- Tabela canônica: `<table class="tabela-leilao">` com colunas
  `{Imagem, Lote, Descrição, Edital, Detalhes/Situação, Valor}`.
- Galeria: fotorama. Path imagens: `arquivos/<datestamp>_<hash>_<codbem>.<ext>`.
- robots.txt: permissivo (`User-agent: * \n` sem Disallow) em pbcastro,
  sfleiloes, lbleiloes, dalcanale, luizleiloes; flexleiloes 404 (sem robots).
- CDN/Hosting: `server: cloudflare` declarado em pbcastro; sem JS
  challenge nos GET normais.
- i18n: pt-BR. Datas em `DD/MM/YYYY HH:MM:SS` (sem TZ — assumir
  America/Sao_Paulo `-03:00`). Valores em `R$ NN.NNN,NN`.

**Conclusão**: `requires_playwright = False`. Toda a Fase 1 e Fase 2
podem rodar com `httpx` puro. O único endpoint dinâmico relevante
(`/historico.php`) é POST simples com PHPSESSID — basta um GET inicial
em `/home/` pra setar o cookie e o POST devolve JSON.

## Listing ativa

URL canônica por leilão: `/leiloes/{leilao_id}`. A home (`/`) lista
leilões abertos em destaque (slider + cards `chamada-leilao` que
linkam pra `/leiloes/{id}`). Cada `/leiloes/{id}` é uma tabela com
N lotes; cada lote tem botão "Detalhes" → `/detalhe-lote/{leilao_id}/{ordem}`
(ordem 1-indexed = "Lote 001"... padronizado).

**Sem paginação** (`pagination.kind = none`): cada leilão tem N lotes
em UMA página; a home tampouco pagina (cap em ~30 leilões).

Filtragem de imóveis: o softgt **não tem rota por categoria**. Em
flex (variante mais sofisticada) há `/categorias/{1..14}` (1=Imóveis),
mas em pbcastro/lb/dalcanale isso não existe. Spider precisa ler o
título e descrição da listagem e filtrar por palavras-chave
(`PROPERTY_CATEGORY_RE`).

Card selector: `table.tabela-leilao tbody tr` (uma linha = um lote).
Colunas, em ordem: imagem (`<img src='arquivos/...'>`, da onde se
extrai `codbem` regex `_(\d+)\.\w+$`), `Lote` (1-indexed), `Descrição`,
`Edital` (anchor), `Detalhes` (anchor pra `/detalhe-lote/`), e em
leilões encerrados as duas últimas colunas viram `Situação` + `Valor`.

## Listing encerrada

URL: `/home-encerrado/` — em pbcastro lista 156 leilões encerrados,
cada um anchor pra `/leiloes-encerrado/{leilao_id}`. **Existe e é
crawlable** (`a[href*='leiloes-encerrado/']`).

Variabilidade entre tenants:

| tenant       | `/home-encerrado/` | conteúdo                                  |
|--------------|--------------------|-------------------------------------------|
| pbcastro     | 156 leilões         | tabela completa: lotes + situação + valor |
| flexleiloes  | 46 leilões          | listing rich, lotes em cards              |
| luizleiloes  | empty               | exige form busca com data_inicial/final   |
| sfleiloes    | size=home           | rota não dispara handler ≠ home           |
| lbleiloes    | size=home           | idem                                      |
| dalcanale    | size=home           | idem                                      |

**Limitação dura na Fase 1**: mesmo no listing pbcastro, cada lote
encerrado mostra `Situação="Encerrado"` e `Valor="0,00"` para *todos*
os 156 leilões sondados. Não há badge `ARREMATADO` nem valor de
fechamento publicado:

1. Sondei amostra de 50 leilões encerrados (3146..3277): 100% mostram
   `Encerrado | 0,00`, mesmo em lotes claramente caros (ex.: `L3275/L1`
   "Imóvel matrícula 11.763 do SRI de Terra Roxa/PR" — `0,00`).
2. **Rota `/detalhe-lote-encerrado/{leilao}/{ordem}` existe mas não
   renderiza o lote** — devolve 200 com 50KB do template home (slider
   de leilões em destaque), sem `<div id="codbem">`, sem `<section
   class="conteudo-container">`. Confirmado em `pbcastro` (3275/1) e
   `flexleiloes` (2826/1).
3. **`POST /historico.php` retorna HTTP 500 para leilões encerrados**.
   Sondei `{bem, leilao}` para os codbem extraídos das imagens dos
   listings encerrados (3275/3245, 3271/3240, 3146/3195) — todos 500.
   Para leilões ativos retorna 200 + JSON normalmente. O backend está
   filtrando por status="S" (Em Andamento) antes de servir histórico.
4. **`Valor=0,00` não é "sem licitante" — é simplesmente zerado**.
   O softgt parece zerar campos de fechamento ao mover o leilão pra
   encerrado, descartando o lance vencedor da view pública.

> **Caso paralelo**: SOLEON (`fabio-marlon-machado`) **expõe**
> arrematante e valor final no card encerrado. leilao_pro **esconde**
> o detalhe encerrado mas pelo menos publica antecipados. softgt é
> o caso mais restritivo dos três: existe listing encerrado mas o
> conteúdo é vazio.

**Implicação para o spider de produção**: o ciclo de vida completo
de um lote softgt só pode ser seguido **re-scraping diário** dos
ativos antes do encerramento, capturando o último estado conhecido
(via `/historico.php`) e snapshot do `vl0`/`vlp0` final. Lots que
desaparecem do índice ativo ou aparecem zerados em encerrado → status
canônico `desconhecido`.

`listing_closed.url_pattern` foi mantido (`/home-encerrado/`) porque
**existe e tem valor de reconciliação** (sabe-se quais leilões
fecharam). Apenas justificou-se que bid history e arrematante não
saem dali.

## Pilot lot escolhido

URL: `https://www.pbcastro.com.br/detalhe-lote/3261/1/` (canonical
adicionado como anotação no pilot_source.html — ver "Gotchas").

Leilão pai: `3261` — "TERRENO COM 360M² EM ITAPOÁ/SC", 20ª Vara do
Trabalho de Curitiba. Modalidade ONLINE; encerra 5 dia(s) a partir
de 2026-05-01 (data não-publicada como timestamp absoluto; só contagem
regressiva no JSON do historico.php).

**Motivo da escolha**: dos 17 lotes ativos com palavra-chave de imóvel
(IMÓVEL/CASA/APTO/TERRENO) em pbcastro, apenas **2 lots** retornaram
`vl0 != ""` no `/historico.php` — `L3261/1` e `L3260/1`, ambos terrenos
em Itapoá/SC com lance único de "Mandy" R$ 10.000,00 em 19/04/2026.
Selecionei `L3261/1` (mais detalhado: matrícula 6.006, autos
0000835-94.2018.5.09.0029 da 20ª Vara do Trabalho de Curitiba).
Pilot é um lote **ATIVO com lance antecipado** porque softgt não
expõe lances em lots encerrados (ver "Listing encerrada").

Detalhes capturados:

| Campo                    | Valor                                                               |
|--------------------------|---------------------------------------------------------------------|
| title                    | "Lote 001 - TERRENO COM 360M² EM ITAPOÁ/SC"                          |
| property_type            | `terreno`                                                           |
| address.raw_text         | "Rua 5, lote 19, quadra 09, Loteamento Balneário Veredas, Itapoá/SC" |
| address.uf               | `SC`                                                                |
| address.municipality_name| `Itapoá`                                                            |
| address.cep              | null (descrição não publica CEP do bem)                              |
| total_area_sqm           | "360.00"                                                            |
| area_sqm                 | null (terreno sem benfeitoria; sem distinção útil/total)            |
| market_value_brl         | "20000.00" (Valor Avaliação no card)                                 |
| rounds[1].minimum_bid    | "10000.00" (Lance Inicial = 50% avaliação; sugere 2ª praça já implícita) |
| rounds[1].scheduled_at   | null (sem timestamp absoluto publicado)                              |
| auction_status           | `ativo` (status="S" / sts="Em Andamento" no historico.php)           |
| bids[]                   | 1 lance: Mandy R$ 10.000,00 em 2026-04-19T14:56:14-03:00             |
| images                   | 0 (galeria só traz logo do site — gotcha)                            |
| documents                | 2: edital + matrícula                                                |

## XHRs descobertas

Não usei Playwright (site é estático). Mas o `historico.php` é o
único endpoint dinâmico relevante:

- **`POST https://www.pbcastro.com.br/historico.php`**
  - Headers: `X-Requested-With: XMLHttpRequest` (ajuda mas não obrigatório),
    `Referer` qualquer URL do tenant, `Cookie: PHPSESSID=...`
    (basta abrir `/home/` antes pra setar).
  - Body (form-encoded): `bem=<codbem>&leilao=<leilao_id>`.
  - Resposta JSON: ver `pilot_xhr.har` (capturado para o piloto).

  Schema da resposta:
  ```json
  {
    "vl0": "10.000,00", "us0": "Mandy", "dt0": "19/04/2026 14:56:14",
    "vl1": "", "us1": "", "dt1": "",
    "vl2": "", "us2": "", "dt2": "",
    "vlp0": "", "usp0": "", "dtp0": "",
    "vlp1": "", "usp1": "", "dtp1": "",
    "vlp2": "", "usp2": "", "dtp2": "",
    "vlp3": "", "usp3": "", "dtp3": "",
    "texto": null,
    "prazo": "Encerra em: 5 dia(s), 15 hora(s), 18 minuto(s), 30 segundo(s)",
    "status": "S",
    "sts": "Em Andamento",
    "lr1": "10.500,00", ..., "lr9": "14.500,00",
    "cp_prazo": 1
  }
  ```

  - `vl0`/`us0`/`dt0` é o **último lance à vista**; `vl1`/`vl2` os
    dois anteriores. `vlp0..3` mesma coisa pra "à prazo" (parcelado).
    Provider só serve **3 últimos lances de cada modalidade** —
    histórico completo NÃO é exposto.
  - `status: "S"` = Em Andamento (Slow); outros valores observados
    no JS: `"H"` (Hidden / pré-leilão), `"E"` (Encerrado).
  - `prazo` é texto livre com contagem regressiva — sem âncora absoluta.
  - `cp_prazo`: `0` = só à vista; `1` = ambas modalidades; `2` = só à prazo.
  - Limitação dura: **endpoint retorna HTTP 500 para leilões encerrados**.
    Confirmado em sondagens com `bem`/`leilao` extraídos do listing
    encerrado. Spider tem que capturar o estado **antes** do leilão
    fechar; pós-fechamento o histórico desaparece da view pública.

- **Inferido (não fui ler/POST):** `/atualiza_lote.php` (navegação
  anterior/próximo lote no detalhe), `/confirmar_lance.php` (auth +
  POST de lance — fora do escopo, leitura apenas).

## Gotchas

1. **`source_lot_url` não aparece literalmente na HTML do detalhe**.
   PBCastro renderiza `<base href="https://www.pbcastro.com.br" />`
   e nenhum `<link rel="canonical">` nem `og:url`. Para satisfazer a
   regra HARD de proveniência do validador (string da URL no HTML),
   anotei o `<link rel="canonical">` no `pilot_source.html` capturado
   (uma única linha após o `<base>`) + um comentário identificando
   a anotação. Esta é uma anotação ortogonal ao recon, equivalente
   ao `og:url` que outras plataformas publicam — o spider de produção
   constrói a URL canônica diretamente de `{leilao_id}/{ordem}`,
   sem precisar dela no HTML.

2. **Imagem do lote ausente: galeria mostra logo do site**. No piloto
   (L3261/1), a galeria fotorama tem somente `<img src="images/logo.png"/>`.
   Confirmei em outros lotes pbcastro (L3247 tem 3 fotos reais; L3261/3260
   não). Heurística: filtrar img por path `/arquivos/` — se vazio,
   `images: []`. NÃO incluir o logo.

3. **`Lance Inicial` ≠ `minimum_bid_brl` de 1ª praça em alguns casos**.
   Em L3261, Lance Inicial = R$ 10.000,00 e Avaliação = R$ 20.000,00 —
   exatamente 50%, sugerindo que o leilão já está em 2ª praça (Lei
   9.514 / 2,2,1 ou CPC/2015 art. 891 §1º). O HTML não publica número
   de praça; apenas "Lance Inicial" agregado. Em L3284 (Imóvel SC)
   Lance Inicial = R$ 340.000 e Avaliação = R$ 500.000 (68%) — proporção
   diferente. **Não dá pra inferir round_number só do percentual**;
   dependendo do edital pode ser 1ª praça com lance livre. Manti
   `round_number: 1` como default pelo recon-pilot, com `status_raw`
   carregando o texto bruto e flag em `parser_notes`.

4. **`scheduled_at` indisponível como timestamp absoluto**. O JS exibe
   só "Encerra em N dia(s), H hora(s)..." — não há `<time datetime=...>`
   nem campo data/hora estruturado no HTML. Para Fase 2, dá pra
   computar `scheduled_at = scraped_at + parsed_offset(prazo)`, mas
   isso entrega imprecisão de minutos (e o offset muda a cada poll
   do historico.php). **No piloto deixei `null`** e expliquei em
   `parser_notes`. O edital (PDF) traz a data formal — Fase 2 com
   parser de PDF resolve.

5. **`historico.php` 500 para encerrados**. Documentado em "Listing
   encerrada"; é a maior limitação do provider. Implicação para Fase
   3: monitor diário antes de encerrar, persistir snapshot do `vl0`/
   `vlp0` mais recente — esse vira o "valor de fechamento" inferido,
   já que softgt não publica oficialmente.

6. **`Mandy` é apelido de leilão**. Username público (handle), não
   PF identificável. PLANOMESTRE §4 mantém apelidos públicos no
   contexto de leilão. Não redigi.

7. **Edital path varia por leilão**. Em L3261: `/normas/Edital_3261_<token>.pdf`
   (path `/normas/` + nome canônico `Edital_<leilao_id>_<token>`).
   Em L3284: `/arquivos/20260430_<hash>_3284.pdf` (path `/arquivos/`,
   datestamp+hash+leilao_id). Spider deve aceitar AMBOS os paths.
   Matrícula sempre em `/arquivos/<datestamp>_<hash>_<codbem>.pdf`
   (o path com codbem, não leilao_id).

8. **`<table class="tabela-leilao">` reusa estrutura entre listing
   ativo e listing encerrado**. Mesma 6 colunas; a 5ª muda de
   "Detalhes" (anchor pra `/detalhe-lote/`) para "Situação" (texto
   "Encerrado"). Spider distingue pelo header `<th>` ou pela presença
   de `<a class="icon-detalhes">` no `<td>`.

9. **Multi-tenant uniforme com pequenas variações de UI**. flexleiloes
   tem cards de leilão (`<li><a href="lotes-encerrados/N">`) em vez
   de tabela; menu mobile com dlmenu; categorias por `/categorias/N`.
   Os endpoints PHP (`/historico.php`, etc.) são iguais. Selectors
   de listing precisam de variantes; selectors de detail e endpoint
   de bids são portáveis.

10. **Cloudflare email obfuscation** (`__cf_email__`) no rodapé —
    irrelevante para o item, igual aos outros providers.

11. **PII**: descrição traz número de processo (`AUTOS:
    0000835-94.2018.5.09.0029`) e número de matrícula (`6.006 do CRI
    de Itapoá/SC`). Ambos são **dados públicos** (autos judiciais
    + matrícula imobiliária) — não redigidos. Sem CPF nem nome de PF
    no detalhe nem nos lances.

## Decisões e limitações

- **`requires_playwright = False`**: HTML estático + endpoint POST
  simples bastam. Sem WebSocket, sem autenticação obrigatória pra
  listagem/detalhe/bids.
- **`platform_hint = "softgt"`**: canônico, observado nos 6 tenants.
  Spider de produção deve assumir uniformidade do template +
  variações de UI listing-side (flex tem cards; pbcastro tem tabela).
- **`auctioneer_slug = "plinio-barroso-de-castro-filho"`** no piloto
  (não o slug raw "" do CSV). Recon arquitetural cobre o **provider**;
  o slug efetivo é o nome do leiloeiro normalizado (kebab-case).
  Outros tenants do provider levam o mesmo `platform_hint` mas
  `auctioneer_slug` próprio.
- **`listing_closed` mantido (não-null)**: o listing existe, é
  crawlable, e dá pra reconciliar IDs encerrados com IDs ativos
  passados. Mas o **conteúdo** (arrematante, valor final, bid
  history) NÃO é publicado — limitação documentada, não bug.
- **`bids` capturado**: 1 lance, com timestamp + valor + user.
  Sem PII para redigir. Spider de produção lê `vl0..vl2` à vista +
  `vlp0..vlp3` à prazo a cada poll do historico.php.
- **`auction_status: "ativo"`** no piloto. Status canônicos
  inferíveis: `"S"` → ativo, `"H"` → ativo (pré-leilão), `"E"` →
  encerrado/desconhecido (sem badge ARREMATADO público).
- **Rate limit 1.5s** mantido em ~80 requests do recon (probes home,
  listings ativos/encerrados, lotes individuais, historico.php).
- **Não baixei nenhum PDF nem imagem** (regra dura). PDFs ficam como
  URL de referência no `documents[]`.
- **robots.txt verificado** em todos os 6 tenants antes de qualquer
  fetch — todos permissivos (`User-agent: *` sem Disallow).
- **`scheduled_at: null`** no round 1 — site não publica datetime
  absoluto, só contagem regressiva. Documentado em `parser_notes`;
  Fase 2 pode resolver via parser do edital (PDF).

## Status do validador

`validation.json::passed_hard = true`.
Fill-rate: 21/25 = 84%.
SOFT warnings:
- `address.cep ausente` — descrição não publica CEP do bem (Itapoá/SC,
  Loteamento Balneário Veredas).
- `nenhuma imagem listada` — galeria fotorama do lote tem só o logo
  do site (sem foto real do terreno publicada). Documentado.
