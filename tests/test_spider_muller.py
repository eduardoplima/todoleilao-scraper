"""Testes do MullerSpider (cobre o BidderLancePlatformSpider via o concrete).

RechSpider usa exatamente o mesmo base — confiamos que se Müller passa,
Rech também passa (config trivial difference).
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest
from leilao_scraper.spiders.muller import MullerSpider
from scrapy.http import HtmlResponse, Request

FIXTURES = Path(__file__).parent / "fixtures" / "muller"


def _response(filename: str, url: str, meta: dict | None = None) -> HtmlResponse:
    body = (FIXTURES / filename).read_bytes()
    return HtmlResponse(
        url=url, body=body, encoding="utf-8", request=Request(url=url, meta=meta or {})
    )


@pytest.fixture
def spider():
    return MullerSpider()


def test_parse_listing_emits_items_and_paginates(spider):
    response = _response("listing_imovel.html", "https://www.mullerleiloes.com.br/lotes/imovel")
    requests = list(spider.parse(response))
    item_reqs = [r for r in requests if "/item/" in r.url]
    page_reqs = [r for r in requests if "page=" in r.url and "/item/" not in r.url]

    assert len(item_reqs) >= 20, f"esperava muitos itens, obteve {len(item_reqs)}"
    # source_listing_url propagado
    assert all(r.meta.get("source_listing_url") == response.url for r in item_reqs)
    # pagination requests existem (max page = 4 conforme HTML)
    assert any(re.search(r"page=2", r.url) for r in page_reqs)


def test_parse_listing_subsequent_page_does_not_paginate(spider):
    """page=2 não dispara descoberta de paginação novamente."""
    response = _response(
        "listing_imovel.html",
        "https://www.mullerleiloes.com.br/lotes/imovel?tipo=imovel&page=2",
    )
    requests = list(spider.parse(response))
    page_reqs = [r for r in requests if "page=" in r.url and "/item/" not in r.url]
    # pagination NÃO é re-emitida (já estamos em page=2)
    assert len(page_reqs) == 0


def test_parse_property_extracts_complete_item(spider):
    response = _response(
        "item_6920.html",
        "https://www.mullerleiloes.com.br/item/6920/detalhes?page=1",
        meta={"source_listing_url": "https://www.mullerleiloes.com.br/lotes/imovel"},
    )
    items = list(spider.parse_property(response))
    assert len(items) == 1
    item = items[0]

    assert item["url"] == response.url
    assert item["auctioneer"] == "mullerleiloes"
    assert item["source_listing_url"] == "https://www.mullerleiloes.com.br/lotes/imovel"

    # property_type — derivado do title "ÁREA RURAL DE 32.000m2 EM SANTIAGO DO SUL/SC"
    # detect_property_type vê "rural" e retorna "rural"
    assert item.get("property_type") == "rural"

    # preços: avaliação e lance inicial
    assert item["market_value"] == Decimal("264000.00")
    assert item["minimum_bid"] == Decimal("264000.00")  # 1ª praça

    # endereço
    addr = item.get("address")
    assert addr is not None
    assert addr["state"] == "SC"
    assert "santiago" in addr["city"].lower()

    # áreas (primeira "X m²" na descrição)
    assert item.get("total_area_sqm")

    # scraped_at
    assert item["scraped_at"]
