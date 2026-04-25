"""Tests do OALeiloesSpider usando fixtures HTML capturadas."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from scrapy.http import HtmlResponse, Request

from leilao_scraper.spiders.oaleiloes import OALeiloesSpider

FIXTURES = Path(__file__).parent / "fixtures" / "oaleiloes"


def _response(filename: str, url: str, meta: dict | None = None) -> HtmlResponse:
    body = (FIXTURES / filename).read_bytes()
    request = Request(url=url, meta=meta or {})
    return HtmlResponse(url=url, body=body, encoding="utf-8", request=request)


@pytest.fixture
def spider():
    return OALeiloesSpider()


# ---- parse_leilao ---------------------------------------------------------

def test_parse_leilao_yields_property_lote_requests_only(spider):
    """O leilão CAIXA tem 100 imóveis. parse_leilao deve emitir Request para
    todos eles (deduplicados) e nenhuma para anchors não-imóveis."""
    response = _response("leilao_361_caixa.html", "https://www.oaleiloes.com.br/leilao/361")
    requests = list(spider.parse_leilao(response))
    assert len(requests) > 30, f"esperava muitos lotes de imóveis, obteve {len(requests)}"
    # todos os requests vão para /lote/{id}
    assert all("/lote/" in r.url for r in requests)
    # source_listing_url é propagado via meta
    assert all(r.meta.get("source_listing_url") == response.url for r in requests)
    # dedup: cada URL é única
    urls = [r.url for r in requests]
    assert len(urls) == len(set(urls))


def test_parse_leilao_skips_non_property_categories(spider):
    """O leilão 363 só tem 1 lote (apartamento). Confirma que filtra direito."""
    response = _response("leilao_363_apto.html", "https://www.oaleiloes.com.br/leilao/363")
    requests = list(spider.parse_leilao(response))
    assert len(requests) == 1
    assert "/lote/14267" in requests[0].url


# ---- parse_property -------------------------------------------------------

def test_parse_property_extracts_full_property_item(spider):
    response = _response(
        "lote_14268_casa.html",
        "https://www.oaleiloes.com.br/lote/14268/al-arapiraca-rua-sob-codigo-municipal-em-arapiraca",
        meta={"source_listing_url": "https://www.oaleiloes.com.br/leilao/361"},
    )
    items = list(spider.parse_property(response))
    assert len(items) == 1
    item = items[0]

    # identidade
    assert item["url"] == response.url
    assert item["auctioneer"] == "oaleiloes"
    assert item["source_listing_url"] == "https://www.oaleiloes.com.br/leilao/361"

    # tipo
    assert item["property_type"] == "casa"

    # preços
    assert item["minimum_bid"] == Decimal("264813.69")
    assert item["market_value"] == Decimal("432486.93")

    # endereço
    addr = item["address"]
    assert addr["state"] == "AL"
    assert addr["city"].lower().startswith("arapiraca")
    assert "RUA SOB CODIGO" in addr["street"].upper()

    # áreas
    assert item["area_sqm"] == Decimal("120.35")
    assert item["total_area_sqm"] == Decimal("200")

    # cômodos
    assert item["bedrooms"] == 3
    assert item["bathrooms"] == 2

    # imagens com path bem_foto
    assert "images" in item
    assert all("bem_foto" in u for u in item["images"])
    assert len(item["images"]) >= 1

    # scraped_at preenchido
    assert item["scraped_at"]
