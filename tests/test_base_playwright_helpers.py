"""Testes dos helpers Playwright em `BaseAuctionSpider.make_request`."""

from __future__ import annotations

from leilao_scraper.spiders.base import BaseAuctionSpider
from scrapy_playwright.page import PageMethod


class _PWSpider(BaseAuctionSpider):
    name = "_pw_helper_test"
    auctioneer_slug = "_pw_helper_test"
    start_urls = ["https://x.com/"]
    requires_playwright = True

    def parse_property(self, response):
        yield {}


class _NonPWSpider(BaseAuctionSpider):
    name = "_nonpw_helper_test"
    auctioneer_slug = "_nonpw_helper_test"
    start_urls = ["https://x.com/"]
    requires_playwright = False

    def parse_property(self, response):
        yield {}


def _methods(req):
    return req.meta.get("playwright_page_methods", [])


def test_wait_for_selector_appends_page_method():
    req = _PWSpider().make_request("https://x.com/", callback=None, wait_for_selector=".lote")
    methods = _methods(req)
    assert len(methods) == 1
    pm = methods[0]
    assert pm.method == "wait_for_selector"
    assert pm.args == (".lote",)
    assert pm.kwargs == {"timeout": 15_000}


def test_wait_timeout_overridable():
    req = _PWSpider().make_request(
        "https://x.com/",
        callback=None,
        wait_for_selector=".x",
        wait_timeout_ms=5_000,
    )
    pm = _methods(req)[0]
    assert pm.kwargs["timeout"] == 5_000


def test_scroll_to_bottom_appends_evaluate_and_networkidle():
    req = _PWSpider().make_request("https://x.com/", callback=None, scroll_to_bottom=True)
    methods = _methods(req)
    assert len(methods) == 2
    assert methods[0].method == "evaluate"
    # primeiro arg é o JS string com loop de scroll progressivo
    assert "scrollHeight" in methods[0].args[0]
    assert methods[1].method == "wait_for_load_state"
    assert methods[1].args == ("networkidle",)


def test_load_more_passes_selector_and_max_clicks():
    req = _PWSpider().make_request(
        "https://x.com/",
        callback=None,
        load_more_selector="button.more",
        load_more_max_clicks=3,
    )
    methods = _methods(req)
    assert len(methods) == 1
    pm = methods[0]
    assert pm.method == "evaluate"
    # JS chama com {sel, maxClicks}
    assert pm.args[1] == {"sel": "button.more", "maxClicks": 3}


def test_helpers_combine_in_canonical_order():
    """page_methods extras → wait → scroll → load_more."""
    custom = [PageMethod("set_extra_http_headers", {"X-Custom": "1"})]
    req = _PWSpider().make_request(
        "https://x.com/",
        callback=None,
        page_methods=custom,
        wait_for_selector=".lote",
        scroll_to_bottom=True,
        load_more_selector="button.more",
    )
    methods = _methods(req)
    assert methods[0].method == "set_extra_http_headers"
    assert methods[1].method == "wait_for_selector"
    assert methods[2].method == "evaluate"  # scroll JS
    assert methods[3].method == "wait_for_load_state"
    assert methods[4].method == "evaluate"  # load_more JS
    assert methods[4].args[1]["sel"] == "button.more"


def test_helpers_noop_when_playwright_off():
    """Spider não-Playwright ignora silenciosamente os helpers."""
    req = _NonPWSpider().make_request(
        "https://x.com/",
        callback=None,
        wait_for_selector=".lote",
        scroll_to_bottom=True,
        load_more_selector="button.more",
    )
    assert "playwright_page_methods" not in req.meta
    assert "playwright" not in req.meta


def test_helpers_apply_when_per_request_opt_in():
    """Mesmo num spider não-Playwright, se a request opta com meta={'playwright': True}
    os helpers passam a valer."""
    req = _NonPWSpider().make_request(
        "https://x.com/",
        callback=None,
        meta={"playwright": True},
        wait_for_selector=".lote",
    )
    methods = _methods(req)
    assert len(methods) == 1
    assert methods[0].method == "wait_for_selector"
