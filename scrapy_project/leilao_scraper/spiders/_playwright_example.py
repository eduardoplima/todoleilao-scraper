"""Spider de validação da infra Playwright — não é um leiloeiro real.

Roda contra `quotes.toscrape.com/js`, um demo público que renderiza as
citações via JavaScript. Sem JS, o HTML inicial não tem nenhum `.quote`;
com JS rodando (Playwright), aparecem 10 quotes por página.

Validação:

  $ scrapy crawl playwright_example
  → deve gerar `data/raw/playwright_example/{ts}.jsonl` com ≥ 10 itens.
  → cada item: {text, author, tags, url}.

Não emite `PropertyItem` (não é imóvel) — desativa as pipelines da casa
via `custom_settings` para evitar `ValidationPipeline` dropar tudo por
falta de `auctioneer` válido.

Helpers do `BaseAuctionSpider` exercitados:
  - `requires_playwright = True`     → injeção automática de meta.
  - `wait_for_selector=".quote"`     → espera o XHR popular a página.

(scroll_to_bottom e load_more_selector estão documentados na classe base
mas não são exercitados aqui — o site é paginado tradicional, não
infinite scroll.)
"""

from __future__ import annotations

from .base import BaseAuctionSpider


class PlaywrightExampleSpider(BaseAuctionSpider):
    name = "playwright_example"
    auctioneer_slug = "playwright_example"
    allowed_domains = ["quotes.toscrape.com"]
    start_urls = ["https://quotes.toscrape.com/js/"]
    requires_playwright = True

    # As pipelines da casa (Validation/Dedup/Enrichment/JsonLinesExport)
    # esperam PropertyItem com `url` e `auctioneer`. Aqui yieldamos dicts
    # genéricos — desativamos pipelines e deixamos só o FEEDS gravar.
    custom_settings = {
        "ITEM_PIPELINES": {},
    }

    def start_requests(self):
        for url in self.start_urls:
            yield self.make_request(
                url,
                callback=self.parse,
                wait_for_selector=".quote",
            )

    def parse(self, response):
        for q in response.css(".quote"):
            yield {
                "text": q.css(".text::text").get("").strip(),
                "author": q.css(".author::text").get("").strip(),
                "tags": q.css(".tag::text").getall(),
                "url": response.url,
            }

        next_href = response.css("li.next a::attr(href)").get()
        if next_href:
            yield self.make_request(
                response.urljoin(next_href),
                callback=self.parse,
                wait_for_selector=".quote",
            )
