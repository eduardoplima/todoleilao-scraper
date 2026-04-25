"""Schema dos itens raspados.

**scrapy.Item** vs dataclass — escolhemos `scrapy.Item` porque:

1. ItemLoader (o ponto principal de manipulação dos campos no `parse()`)
   é nativo de scrapy.Item — usa `Field()` metadata. Com dataclass dá pra
   funcionar via itemadapter, mas perde-se a expressividade.
2. O projeto é Scrapy-centrado; não há lugar fora do pipeline onde a
   tipagem estática agregaria valor real.
3. Pipelines (`itemadapter`) tratam scrapy.Item de forma idiomática.

Schema canônico definido em CLAUDE.md. Campos vazios viram `None` ou
sequência vazia conforme o caso; pipelines a jusante validam.
"""

from __future__ import annotations

import scrapy


class PropertyItem(scrapy.Item):
    # ----- identidade --------------------------------------------------------
    url = scrapy.Field()  # chave primária do item
    auctioneer = scrapy.Field()  # slug do leiloeiro (ex.: 'frazao_leiloes')
    source_listing_url = scrapy.Field()  # URL da página de listagem que originou o item

    # ----- conteúdo textual --------------------------------------------------
    title = scrapy.Field()
    description = scrapy.Field()
    property_type = scrapy.Field()  # apartamento|casa|terreno|comercial|rural|outro

    # ----- endereço (dict) ---------------------------------------------------
    # {street, number, complement, neighborhood, city, state, zip}
    address = scrapy.Field()

    # ----- áreas (Decimal m²) ------------------------------------------------
    area_sqm = scrapy.Field()  # área útil
    total_area_sqm = scrapy.Field()  # área total / terreno

    # ----- características (int) ---------------------------------------------
    bedrooms = scrapy.Field()
    bathrooms = scrapy.Field()
    parking_spots = scrapy.Field()

    # ----- valores (Decimal BRL) ---------------------------------------------
    minimum_bid = scrapy.Field()  # lance mínimo
    market_value = scrapy.Field()  # valor de avaliação
    discount_pct = scrapy.Field()  # calculado pela EnrichmentPipeline

    # ----- leilão ------------------------------------------------------------
    auction_phase = scrapy.Field()  # 1a_praca|2a_praca|unica
    first_auction_date = scrapy.Field()  # ISO 8601 com timezone
    second_auction_date = scrapy.Field()
    status = scrapy.Field()  # aberto|arrematado|cancelado|desconhecido

    # ----- mídia / anexos ----------------------------------------------------
    images = scrapy.Field()  # list[str] de URLs absolutas
    documents = scrapy.Field()  # list[{name, url}]

    # ----- diagnóstico -------------------------------------------------------
    raw_html_snapshot = scrapy.Field()  # opcional, para debug
    scraped_at = scrapy.Field()  # ISO 8601, preenchido pelo loader/pipeline
