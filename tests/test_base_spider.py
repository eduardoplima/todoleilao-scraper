"""Testes do `BaseAuctionSpider` e do `DummySpider`."""

from __future__ import annotations

from decimal import Decimal

import pytest
import scrapy
from leilao_scraper.spiders.base import BaseAuctionSpider
from leilao_scraper.spiders.dummy import DummySpider
from scrapy.http import HtmlResponse, Request

HTML_DUMMY = b"""<!doctype html><html><head><title>Example</title></head>
<body><h1>Example Domain</h1></body></html>"""


def _response(url: str, meta: dict | None = None) -> HtmlResponse:
    request = Request(url=url, meta=meta or {})
    return HtmlResponse(url=url, body=HTML_DUMMY, encoding="utf-8", request=request)


# ---- spider de teste ------------------------------------------------------


class _PWSpider(BaseAuctionSpider):
    name = "pw_test"
    auctioneer_slug = "pw_test"
    start_urls = ["https://example.com/"]
    requires_playwright = True

    def parse_property(self, response):
        yield {"ok": True}


class _NonPWSpider(BaseAuctionSpider):
    name = "nonpw_test"
    auctioneer_slug = "nonpw_test"
    start_urls = ["https://example.com/"]
    requires_playwright = False

    def parse_property(self, response):
        yield {"ok": True}


# ---- make_request ---------------------------------------------------------


def test_make_request_injects_playwright_when_required():
    spider = _PWSpider()
    req = spider.make_request("https://x.com/", callback=spider.parse_property)
    assert isinstance(req, scrapy.Request)
    assert req.meta.get("playwright") is True


def test_make_request_omits_playwright_when_not_required():
    spider = _NonPWSpider()
    req = spider.make_request("https://x.com/", callback=spider.parse_property)
    assert "playwright" not in req.meta


def test_make_request_preserves_user_meta_and_kwargs():
    spider = _PWSpider()
    req = spider.make_request(
        "https://x.com/",
        callback=spider.parse_property,
        meta={"source_listing_url": "https://l.com/"},
        priority=5,
        dont_filter=True,
    )
    assert req.meta["source_listing_url"] == "https://l.com/"
    assert req.meta["playwright"] is True
    assert req.priority == 5
    assert req.dont_filter is True


def test_make_request_user_can_explicit_disable_playwright_per_request():
    """Mesmo num spider Playwright, dá pra opt-out de uma request específica."""
    spider = _PWSpider()
    req = spider.make_request(
        "https://x.com/",
        callback=spider.parse_property,
        meta={"playwright": False},
    )
    # setdefault não sobrescreve — usuário tem a última palavra
    assert req.meta["playwright"] is False


# ---- new_loader -----------------------------------------------------------


def test_new_loader_prefills_url_and_auctioneer():
    spider = _NonPWSpider()
    response = _response("https://example.com/lote/1")
    loader = spider.new_loader(response)
    item = loader.load_item()
    assert item["url"] == "https://example.com/lote/1"
    assert item["auctioneer"] == "nonpw_test"
    # source default = response.url quando nada foi passado
    assert item["source_listing_url"] == "https://example.com/lote/1"


def test_new_loader_picks_source_from_meta():
    spider = _NonPWSpider()
    response = _response(
        "https://example.com/lote/1",
        meta={"source_listing_url": "https://example.com/leilao/9"},
    )
    item = spider.new_loader(response).load_item()
    assert item["source_listing_url"] == "https://example.com/leilao/9"


def test_new_loader_explicit_source_takes_precedence_over_meta():
    spider = _NonPWSpider()
    response = _response(
        "https://example.com/lote/1",
        meta={"source_listing_url": "https://example.com/leilao/9"},
    )
    item = spider.new_loader(
        response, source_listing_url="https://example.com/categoria/imoveis"
    ).load_item()
    assert item["source_listing_url"] == "https://example.com/categoria/imoveis"


# ---- parse_property hook --------------------------------------------------


def test_parse_property_default_raises_not_implemented():
    """Subclasses esquecidas devem falhar barulhento, não silenciosamente."""

    class _Empty(BaseAuctionSpider):
        name = "empty"
        auctioneer_slug = "empty"
        start_urls = ["https://x.com/"]

    spider = _Empty()
    with pytest.raises(NotImplementedError, match="parse_property"):
        list(spider.parse_property(_response("https://x.com/")))


# ---- log_event ------------------------------------------------------------


def test_log_event_emits_structured_format(caplog):
    spider = _NonPWSpider()
    with caplog.at_level("INFO", logger="nonpw_test"):
        spider.log_event("lote_skipped", url="https://x.com/lote/1", reason="non_property")
    msg = caplog.records[-1].getMessage()
    assert msg.startswith("event=lote_skipped")
    assert "url=" in msg
    assert "reason=non_property" in msg


def test_log_event_quotes_strings_with_spaces(caplog):
    spider = _NonPWSpider()
    with caplog.at_level("INFO", logger="nonpw_test"):
        spider.log_event("err", message="connection reset by peer")
    msg = caplog.records[-1].getMessage()
    assert "message='connection reset by peer'" in msg


# ---- DummySpider integração ----------------------------------------------


def test_dummy_spider_yields_complete_item():
    spider = DummySpider()
    response = _response("https://example.com/")
    items = list(spider.parse_property(response))
    assert len(items) == 1
    item = items[0]
    assert item["auctioneer"] == "dummy"
    assert item["url"] == "https://example.com/"
    assert item["property_type"] == "apartamento"
    assert item["minimum_bid"] == Decimal("100000.00")
    assert item["market_value"] == Decimal("250000.00")
    assert item["first_auction_date"] == "2026-05-15T14:00:00-03:00"


def test_dummy_spider_parse_yields_request():
    """parse() deve enfileirar um request via make_request."""
    spider = DummySpider()
    response = _response("https://example.com/")
    requests = list(spider.parse(response))
    assert len(requests) == 1
    req = requests[0]
    assert req.url == "https://example.com/"
    # source_listing_url propagado via meta
    assert req.meta.get("source_listing_url") == "https://example.com/"
    # dummy não usa playwright
    assert "playwright" not in req.meta
