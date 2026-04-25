# Todo Leilão Scraper

Sistema de raspagem de imóveis em leilão a partir de leiloeiros oficiais brasileiros, partindo da lista pública mantida pelo INNLEI (Instituto Nacional dos Leiloeiros).

---

## Objetivo

Construir um pipeline que, ao final, produza uma base unificada de imóveis em leilão, com os seguintes passos:

1. **Descoberta** — extrair a lista completa de leiloeiros do site `https://innlei.org.br/leiloeiros` (paginado).
2. **Filtragem** — separar leiloeiros que atuam com leilão de imóveis.
3. **Análise de sites** — para cada leiloeiro, classificar o site (HTML estático vs. JS dinâmico) e localizar a(s) página(s) de listagem de imóveis.
4. **Spiders Scrapy** — criar um spider dedicado para cada site, usando Playwright nos casos que exigirem renderização JS.
5. **Normalização** — consolidar todos os imóveis em um schema único.

---

## Stack

- **Python 3.11+**
- **Scrapy** — framework principal de raspagem
- **scrapy-playwright** — renderização de páginas JS
- **httpx + BeautifulSoup** — usados na fase de descoberta e análise (mais leves que Scrapy para tarefas pontuais)
- **pandas** — manipulação dos artefatos intermediários (CSVs/JSONs)
- **rich / loguru** — logs e CLI

---

## Estrutura de Pastas

```
todo-leilao-scraper/
├── CLAUDE.md
├── PROMPTS.md
├── pyproject.toml
├── README.md
├── discovery/
│   ├── __init__.py
│   ├── innlei_scraper.py        # extrai leiloeiros do innlei
│   ├── filter_real_estate.py    # filtra leiloeiros de imóveis
│   ├── site_analyzer.py         # classifica HTML vs JS
│   └── listing_finder.py        # localiza páginas de imóveis
├── scrapy_project/
│   ├── scrapy.cfg
│   └── leilao_scraper/
│       ├── __init__.py
│       ├── items.py
│       ├── pipelines.py
│       ├── middlewares.py
│       ├── settings.py
│       ├── spiders/
│       │   ├── __init__.py
│       │   ├── base.py          # BaseAuctionSpider
│       │   └── ...              # um arquivo por leiloeiro
│       └── loaders.py
├── data/
│   ├── raw/                     # saídas brutas dos spiders
│   ├── processed/               # dados normalizados
│   └── intermediate/            # CSVs da fase de descoberta
└── reports/
    └── site_analysis.md         # relatório de classificação dos sites
```

---

## Schema do Item (Property)

Campos canônicos para qualquer imóvel raspado:

- `url` — URL da página do imóvel (chave primária)
- `auctioneer` — slug do leiloeiro (ex.: `frazao_leiloes`)
- `source_listing_url` — URL da listagem de origem
- `title` — título do imóvel
- `description` — descrição completa
- `property_type` — `apartamento` | `casa` | `terreno` | `comercial` | `rural` | `outro`
- `address` — `{street, number, complement, neighborhood, city, state, zip}`
- `area_sqm` — área útil em m²
- `total_area_sqm` — área total em m²
- `bedrooms`, `bathrooms`, `parking_spots` — inteiros
- `minimum_bid` — lance mínimo (BRL, decimal)
- `market_value` — valor de avaliação (BRL, decimal)
- `discount_pct` — calculado, % desconto sobre avaliação
- `auction_phase` — `1a_praca` | `2a_praca` | `unica`
- `first_auction_date`, `second_auction_date` — ISO 8601
- `status` — `aberto` | `arrematado` | `cancelado` | `desconhecido`
- `images` — lista de URLs
- `documents` — lista de `{name, url}` (edital, matrícula, laudo)
- `raw_html_snapshot` — opcional, para debug
- `scraped_at` — timestamp ISO 8601

---

## Convenções

- **Spider naming**: `{slug_do_leiloeiro}` em snake_case (ex.: `frazao_leiloes`, `mega_leiloes`).
- **Item Loaders** para toda normalização — nunca normalizar dentro do `parse()`.
- **Moedas em BRL** convertidas para `Decimal` (string `"123456.78"`).
- **Datas em ISO 8601** com timezone (`-03:00`).
- **Spiders JS** levam o atributo `requires_playwright = True`.
- **robots.txt** sempre respeitado (`ROBOTSTXT_OBEY = True`); exceções documentadas no spider.
- **Rate limiting**: `DOWNLOAD_DELAY = 1.5` por padrão, ajustado por spider quando necessário.
- **User-Agent** identificável (`TodoLeilaoBot/1.0 (+contato)`).

---

## Fases do Projeto

| Fase | Saída |
|------|-------|
| 1. Descoberta | `data/intermediate/auctioneers_raw.csv` |
| 2. Filtragem | `data/intermediate/auctioneers_real_estate.csv` |
| 3. Análise de sites | `data/intermediate/site_analysis.csv` + `reports/site_analysis.md` |
| 4. Setup Scrapy | projeto Scrapy funcional, item, pipelines |
| 5. Spiders HTML | spiders dos sites estáticos rodando |
| 6. Spiders JS | spiders Playwright rodando |
| 7. Pipeline final | dataset consolidado em `data/processed/properties.parquet` |

---

## Considerações Legais e Éticas

- Verificar **termos de uso** de cada site antes de criar spider.
- Respeitar `robots.txt`.
- Os dados de leilão são, em sua maioria, **públicos** (publicidade obrigatória do edital), mas redistribuição comercial pode ter restrições.
- Não automatizar lances nem qualquer ação além de leitura.
- Não burlar captchas ou autenticações.

---

## Pendências Conhecidas

- [ ] Estratégia para sites que exigem captcha (provavelmente ignorar nesta v1).
- [ ] Geocoding de endereços (fase posterior).
- [ ] Deduplicação entre leiloeiros que listam o mesmo imóvel.
- [ ] Monitoramento de mudanças de status (precisaria de re-scrape periódico + diff).