"""Testes do MoaciraSpider com fixtures HTML capturadas."""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest
from scrapy.http import HtmlResponse, Request

from leilao_scraper.spiders.moacira import MoaciraSpider

FIXTURES = Path(__file__).parent / "fixtures" / "moacira"


def _response(filename: str, url: str, meta: dict | None = None) -> HtmlResponse:
    body = (FIXTURES / filename).read_bytes()
    request = Request(url=url, meta=meta or {})
    return HtmlResponse(url=url, body=body, encoding="utf-8", request=request)


@pytest.fixture
def spider():
    return MoaciraSpider()


# ---- parse_listing -------------------------------------------------------

def test_listing_emits_property_lotes_and_paginates(spider):
    """Página 1 emite Request pra cada lote + Request para páginas 2..max."""
    response = _response(
        "leilao_730_caixa.html", "https://www.moacira.lel.br/leilao/730"
    )
    requests = list(spider.parse_listing(response))

    page_re = re.compile(r"/leilao/\d+/\d+$")
    lote_reqs = [r for r in requests if "/lote/" in r.url]
    page_reqs = [r for r in requests if page_re.search(r.url)]

    assert len(lote_reqs) >= 40, f"esperava muitos lotes, obteve {len(lote_reqs)}"
    # Pagination requests existem (até a max page = 10)
    assert len(page_reqs) > 5
    page_urls = {r.url for r in page_reqs}
    assert "https://www.moacira.lel.br/leilao/730/2" in page_urls
    assert "https://www.moacira.lel.br/leilao/730/10" in page_urls
    # source_listing_url propagado
    assert all(r.meta.get("source_listing_url") == response.url for r in lote_reqs)


def test_listing_subsequent_page_does_not_re_paginate(spider):
    """Páginas 2..N só emitem lotes (paginação só na chamada inicial)."""
    response = _response(
        "leilao_730_p10.html", "https://www.moacira.lel.br/leilao/730/10"
    )
    requests = list(spider.parse_listing(response, current_page=10))
    page_reqs = [r for r in requests if r.url.endswith("/10")]
    # nenhum request de "outra página" aqui
    assert all("/leilao/730/" not in r.url or r.url.endswith("/10") for r in requests)
    # mas deve emitir os lotes da página 10
    lote_reqs = [r for r in requests if "/lote/" in r.url]
    assert len(lote_reqs) >= 10


# ---- parse_property -------------------------------------------------------

def test_parse_property_extracts_complete_item(spider):
    response = _response(
        "lote_10763_casa.html",
        "https://www.moacira.lel.br/lote/10763/casa-em-b-arapiraca-al-b-p-endereco-rua-em-arapiraca",
        meta={"source_listing_url": "https://www.moacira.lel.br/leilao/730"},
    )
    items = list(spider.parse_property(response))
    assert len(items) == 1
    item = items[0]

    # identidade
    assert item["url"] == response.url
    assert item["auctioneer"] == "moacira_tegoni_goedert"
    assert item["source_listing_url"] == "https://www.moacira.lel.br/leilao/730"

    # tipo veio do slug (mais confiável que parse de description)
    assert item["property_type"] == "casa"

    # preços do .destaque
    assert item["market_value"] == Decimal("189000.00")
    assert item["minimum_bid"] == Decimal("114234.15")

    # endereço extraído da descrição
    addr = item["address"]
    assert addr["state"] == "AL"
    assert addr["city"].lower() == "arapiraca"
    assert "ANTONIA LEAO" in addr["street"].upper()

    # áreas
    assert item["area_sqm"] == Decimal("98.66")
    assert item["total_area_sqm"]  # 202,71 (terreno) ou 98,66 (total) — qualquer um é válido

    # cômodos
    assert item["bedrooms"] == 3
    assert item["bathrooms"] == 2
    assert item["parking_spots"] == 1

    # imagens — moacira tem fotos da CAIXA externamente
    assert item.get("images")
    assert any("caixa.gov.br" in u or "bem_foto" in u for u in item["images"])

    # scraped_at preenchido
    assert item["scraped_at"]


def test_parse_property_handles_missing_destaque_gracefully(spider):
    """Quando .destaque não existe, item ainda sai sem preço — não levanta."""
    minimal_html = (
        "<html><head><title>Moacira | Casa em X/SP</title></head>"
        "<body><div class='col-8 py-3'>DESCRIÇÃO COMPLETA</div></body></html>"
    )
    response = HtmlResponse(
        url="https://www.moacira.lel.br/lote/9999/casa-em-x",
        body=minimal_html.encode("utf-8"),
        encoding="utf-8",
        request=Request("https://www.moacira.lel.br/lote/9999/casa-em-x"),
    )
    items = list(spider.parse_property(response))
    assert len(items) == 1
    item = items[0]
    # tipo vem do slug
    assert item["property_type"] == "casa"
    # preços ausentes → campos não populados (não None com erro)
    assert "minimum_bid" not in item
    assert "market_value" not in item
