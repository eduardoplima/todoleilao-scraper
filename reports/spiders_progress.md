# Spiders — progresso

Status dos spiders concretos do `leilao_scraper`. Smokes rodados com
`scrapy crawl <name> -s CLOSESPIDER_ITEMCOUNT=20`, AutoThrottle ativo,
`DOWNLOAD_DELAY=1.5`, `ROBOTSTXT_OBEY=True`. Saídas em
`data/raw/<name>/{ts}.jsonl`.

## Resumo

| spider     | leiloeiro                                  | UF      | status | itens (smoke) | completos | observações                                              |
| ---------- | ------------------------------------------ | ------- | :----: | ------------: | --------: | -------------------------------------------------------- |
| `dummy`    | (fixture)                                  | —       | ok     |             1 |     1/1   | valida o esqueleto Validation→Dedup→Enrich→Export        |
| `oaleiloes`| Bruno Duarte / Orlando Araújo (OALeilões)  | DF      | ok     |            24 |    19/24  | descrição mais "frouxa" — ~20% caem em property_type=None |
| `moacira`  | Moacira Tegoni Goedert                     | DF      | ok     |            42 |    42/42  | **piloto**, 100% completos, slug→property_type            |
| `muller`   | Darci Muller / Daniel Costa Müller         | RS      | ok     |            36 |    34/36  | bidder/lance, 1ª praça começa em market_value (disc=0%)   |
| `rech`     | Alexandre Rech                             | RS      | ok     |            26 |    21/26  | bidder/lance, 5/26 sem cidade no padrão Cidade:X/UF       |
| `cassiano` | Cassiano Ricardo Dall Ago e Silva          | PI      | parcial|            51 |     1/51  | bidder/lance — site **não expõe market_value publicamente** |

"Completos" = item com `property_type` + `minimum_bid` + `market_value` + `address` simultaneamente preenchidos.

## Plataformas detectadas

A escolha dos primeiros 5 leiloeiros foi deliberada para cobrir três plataformas
distintas e validar a arquitetura de reuso:

### 1. `leiloar / blast!web` — `oaleiloes`, `moacira`
Identificador: comentário no `robots.txt` (`plataforma leiloar e blast!web`).
URLs `/leilao/{id}` (página agregadora) → `/lote/{id}/{slug}` (detalhe).
Paginação **por path** (`/leilao/{id}/N`). Selectors `.destaque` e `.col-8.py-3`
no detalhe. moacira refatorou pra extração estruturada; oaleiloes ainda usa
extração por regex no body_text (anterior ao moacira) — funciona mas com
~20% de queda em campos opcionais.

### 2. `bidder/lance` — `muller`, `rech`, `cassiano`
URLs `/lotes/{categoria}` (paginação `?page=N`) → `/item/{id}/detalhes?page=1`.
Lógica concentrada em `spiders/_bidder_lance_platform.py` (não-spider, prefixo
`_`). As três subclasses concretas têm 4 linhas cada — só configuração de
domínio, slug e start_urls.

| spider     | linhas | métricas smoke (/51 ou /36) |
| ---------- | -----: | -------------------------- |
| `muller`   |     12 | endereços + preços OK      |
| `rech`     |     10 | endereços + preços OK      |
| `cassiano` |     10 | preços OK; **avaliação não exposta** no site (apenas lance mínimo) |

### 3. (não cobertos) Plataformas Vue/Nuxt + Superbid
`leiloesjudiciaismg`, `superbid`, `Mega Leilões`, `kcleiloes` (via bomvalor).
Estes ficam para o próximo bloco — exigem investigação separada e
provavelmente Playwright (dynamic).

## Top 10 ordens próximas

Baseado no `reports/site_analysis.md` (bucket 1 — static):

| # | leiloeiro                       | site                            | items | plataforma                  | esforço estimado |
|--:| ------------------------------- | ------------------------------- | ----:| --------------------------- | ---------------- |
| 1 | Kátia Cerqueira da Silva Casaes | kcleiloes.com.br → bomvalor     |  162 | bomvalor (multi-tenant)     | médio (redirect) |
| 2 | LEVY DOS SANTOS MORAES FILHO    | santosmoraesleiloes.com.br      |  130 | leiloessantosmoraes (terc)  | médio (redirect) |
| 3 | Thaís Costa Bastos Teixeira     | leiloesjudiciaismg.com.br       |  105 | Vue + Nuxt + Superbid       | alto (talvez JS) |
| 4 | SÉRGIO DE PAULA PEREIRA         | esleiloes.com.br                |   98 | (a investigar)              | baixo            |
| 5 | VICENTE/Mariana                 | vipleiloes.com.br               |   84 | (a investigar; 3 leiloeiros)| baixo (multi)    |
| 6 | Rodolfo Schmitz                 | hammer.lel.br                   |   60 | (custom — lista vazia em SSR; **JS-rendered listing**) | médio (Playwright) |
| 7 | ANGELICA / Angela               | lancetotal.com.br               |   60 | bidder-like                 | baixo            |
| 8 | Italo Trindade Moura Filho      | italoleiloes.com (hybrid)       |  101 | hybrid (bucket 2)           | médio            |
| 9 | José Luiz Pereira Vizeu         | flexleiloes.com.br (dynamic)    |   40 | Next.js                     | alto (Playwright) |
|10 | Outras `*.leilao.br`            | shopleiloes.leilao.br etc.      | varia| leilao.br platform          | baixo (refatoro) |

## Decisões de arquitetura

1. **Spiders compartilham base** (`BaseAuctionSpider`): identidade do leiloeiro,
   `make_request` com injeção de meta playwright, `new_loader` com pré-fill,
   `parse_property` como hook obrigatório, `log_event` para tracing estruturado.
2. **Plataformas multi-leiloeiro** ganham um arquivo `_<plataforma>.py`
   prefixado com `_` para não ser carregado como spider. Subclasses concretas
   são triviais (4–10 linhas).
3. **Detecção de tipo via slug da URL** — sempre que possível (ex.: moacira
   `/lote/.../casa-em-...`). Mais confiável que parser de descrição.
4. **Filtro de imagens por exclusão** — `EXCLUDED = (logomarca, banner,
   icones, favicon)` + extensão. Cobre os assets do site sem precisar
   conhecer o caminho específico das fotos do bem.
5. **HTTPCACHE** ativo em settings — re-runs do mesmo crawl são ~3x mais
   rápidos. Cache em `data/intermediate/cache/scrapy_httpcache/`.

## Limitações conhecidas (a tratar)

- **`oaleiloes` parsing por body_text** ainda gera ~20% de items sem
  `property_type`. Refatorar para usar a estrutura `.destaque`/`.col-8`
  como o `moacira` faz pode subir essa taxa.
- **`cassiano` sem `market_value`** — o site simplesmente não publica
  avaliação na página pública; só "Mínimo: R$X". `discount_pct` fica `None`
  para todos os itens. Sem solução até o site mudar a postura.
- **`muller`/`rech` `discount_pct = 0%`** — capturamos `Lance Inicial` da
  1ª praça, que tipicamente == `Valor de Avaliação`. A 2ª praça (com
  desconto real) está na mesma página mas não é capturada. Refactor:
  capturar o *segundo* `Lance Inicial` como `minimum_bid` quando há `2ª
  praça`, e expor `auction_phase` corretamente.
- **`hammer.lel.br`** parecia ser leiloar/blast! pelo TLD `.lel.br`, mas
  é uma plataforma client-side (lista de lotes vazia em SSR). Vai para
  o bucket 2 (Playwright).

## Como rodar

```sh
# Roda um spider específico até 20 itens (smoke)
cd scrapy_project
uv run scrapy crawl moacira -s CLOSESPIDER_ITEMCOUNT=20

# Lista todos os spiders disponíveis
uv run scrapy list

# Roda full crawl (atenção: longo — moacira tem 471 lotes)
uv run scrapy crawl moacira

# Os feeds saem em data/raw/<spider>/<timestamp>.jsonl
```
