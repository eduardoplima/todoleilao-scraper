"""DummySpider — valida que `BaseAuctionSpider` está cabladofim a fim.

Não deve ser ativado em produção (não está no `ITEM_PIPELINES` skip-list,
mas o item gerado tem `auctioneer="dummy"` e é facilmente filtrado a jusante).
Roda em ~3 s com `scrapy crawl dummy`:

  - bate em `https://example.com/` (página estável e leve);
  - exercita `make_request` (passando meta=source_listing_url);
  - exercita `new_loader` (preenche identidade automaticamente);
  - exercita `parse_property` (hook obrigatório, faz add_value de
    title/property_type/preços/scraped_at);
  - exercita o ITEM_PIPELINES inteiro (Validation→Dedup→Enrich→Export).
"""

from __future__ import annotations

from .base import BaseAuctionSpider


class DummySpider(BaseAuctionSpider):
    name = "dummy"
    auctioneer_slug = "dummy"
    allowed_domains = ["example.com"]
    start_urls = ["https://example.com/"]
    requires_playwright = False

    def parse(self, response):
        # Demonstra que make_request encaminha kwargs e meta corretamente.
        yield self.make_request(
            response.url,
            callback=self.parse_property,
            meta={"source_listing_url": response.url},
            dont_filter=True,  # mesma URL da start — sem dont_filter o dedup do scheduler descarta
        )

    def parse_property(self, response):
        loader = self.new_loader(response)
        loader.add_value("title", "DUMMY APARTAMENTO 2 dorm 80m²")
        loader.add_value("description", "<p>Imóvel dummy só para validar o esqueleto.</p>")
        loader.add_value("property_type", "Apartamento de teste")
        loader.add_value("minimum_bid", "R$ 100.000,00")
        loader.add_value("market_value", "R$ 250.000,00")
        loader.add_value("first_auction_date", "15/05/2026 às 14h00")
        loader.add_value("status", "aberto")
        loader.add_value("scraped_at", self.now_iso())
        self.log_event("dummy_item_emitted", url=response.url)
        yield loader.load_item()
