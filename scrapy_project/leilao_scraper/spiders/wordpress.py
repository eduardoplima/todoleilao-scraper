"""Spider genérico para tenants WordPress/WooCommerce.

10 sites em data/intermediate/site_providers.csv usam WordPress + plugin
WooCommerce para listar leilões. A estrutura varia por tema, mas o
backbone segue:
  - Catálogo em `/loja/` ou `/categoria-produto/{slug}/` (paginação `?paged=N`).
  - Detalhe em `/produto/{slug}/` com `<h1 class="product_title">`.
  - Preços em texto plano: "AVALIAÇÃO: R$ N", "LANCE MÍNIMO: R$ N",
    "PRIMEIRO E SEGUNDO LEILÃO: R$ N" — extração via regex.

UA padrão de bot é frequentemente bloqueado (HTTP 406). Forçamos UA
de browser real.

Uso:
    scrapy crawl wordpress -a sites=1
    scrapy crawl wordpress -a sites=all
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import scrapy

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _detail_is_imovel,
    _dedup_clauses,
    _extract_auctioneer,
    _find_edital_url,
    _normalize_text,
    _parse_auction_clauses,
    _pdf_to_text,
)


_PRODUCT_HREF_RE = re.compile(r"/produto/([^/?#]+)/?")
_AVALIACAO_RE = re.compile(r"AVALIA[CÇ][AÃ]O[^R]{0,30}R\$\s*([\d.,]+)", re.I)
_LANCE_MIN_RE = re.compile(
    r"(?:LANCE\s+M[ÍI]NIMO|PRIMEIRO\s+E\s+SEGUNDO\s+LEIL[ÃA]O|"
    r"SEGUNDO\s+LEIL[ÃA]O|VALOR\s+M[ÍI]NIMO)[^R]{0,80}R\$\s*([\d.,]+)",
    re.I,
)
from leilao_scraper.spiders._common_ua import BROWSER_USER_AGENT as _BROWSER_UA


class WordpressSpider(ProviderSpider):
    name = "wordpress"
    provider_slug = "wordpress"
    auctioneer_slug = "wordpress"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
        "USER_AGENT": _BROWSER_UA,
        # WP themes podem bloquear UA bot; força UA browser também na fase
        # de robots.txt e starts.
        "DEFAULT_REQUEST_HEADERS": {
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        },
    }

    MAX_PAGES_PER_HOST = 30

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._host_seen: dict[str, set[str]] = {}

    def start_requests(self) -> Iterable[scrapy.Request]:
        self._open_incremental_db()
        yield from super().start_requests()

    def closed(self, reason: str) -> None:
        self.close_incremental_db()

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        seen = self._host_seen.setdefault(host, set())
        kept = 0
        for href in response.css("a[href*='/produto/']::attr(href)").getall():
            if not _PRODUCT_HREF_RE.search(href):
                continue
            absolute = response.urljoin(href)
            if self.host_of(absolute) != host:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            kept += 1
            m_slug = _PRODUCT_HREF_RE.search(absolute)
            lot_code = m_slug.group(1) if m_slug else None
            if lot_code and self.lot_exists(host, lot_code):
                yield self.make_listing_only_item(
                    url=absolute,
                    source_lot_code=lot_code,
                    auctioneer=f"wordpress::{host}",
                )
                continue
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url, "host": host},
            )
        page = response.meta.get("page", 1)
        self.log_event("wp_listing_done", host=host, kept=kept, page=page)

        # Paginação WP: ?paged=N ou /page/N/
        if kept > 0 and page < self.MAX_PAGES_PER_HOST:
            base = response.url.rstrip("/").split("?")[0]
            next_url = f"{base}/page/{page + 1}/"
            yield self.make_request(
                next_url,
                callback=self.parse,
                meta={"host": host, "page": page + 1},
            )

    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("host", self.host_of(response.url))
        h1 = (response.css("h1.product_title::text, h1.entry-title::text, h1::text").get() or "").strip()
        og_title = response.css("meta[property='og:title']::attr(content)").get() or h1
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""

        body_text = _normalize_text(" ".join(response.css(
            "div.woocommerce-product-details__short-description *::text, "
            "div.product_description *::text, "
            "div.summary *::text, "
            "div.entry-content *::text, "
            "body *::text"
        ).getall()))

        if not _detail_is_imovel(og_title or h1, og_desc + " " + body_text[:2000]):
            self.log_event("wp_lote_dropped_non_imovel", url=response.url,
                           title=(og_title or h1)[:80])
            return

        loader = self.new_loader(response)
        auctioneer = _extract_auctioneer(response)
        if auctioneer and auctioneer.get("full_name"):
            loader.replace_value("auctioneer", auctioneer["full_name"])
            loader.add_value("auctioneer_data", auctioneer)
        else:
            loader.replace_value("auctioneer", f"wordpress::{host}")

        m_slug = _PRODUCT_HREF_RE.search(response.url)
        if m_slug:
            loader.add_value("source_lot_code", m_slug.group(1))

        if h1 or og_title:
            loader.add_value("title", (h1 or og_title).strip())

        desc = og_desc
        if not desc or len(desc) < 30:
            short = " ".join(response.css(
                "div.woocommerce-product-details__short-description *::text"
            ).getall())
            desc = _normalize_text(short) or body_text[:5000]
        if desc:
            loader.add_value("description", desc[:10000])

        # status — heurística mínima
        bl = body_text.lower()
        if "arrematado" in bl or "vendido" in bl:
            status = "arrematado"
        elif "encerrad" in bl or "finalizad" in bl:
            status = "desconhecido"
        elif "suspens" in bl:
            status = "suspenso"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Preço mínimo
        m_min = _LANCE_MIN_RE.search(body_text)
        if m_min:
            try:
                loader.add_value("minimum_bid", str(_brl_to_decimal(m_min.group(1))))
            except Exception:
                pass

        # Avaliação
        m_av = _AVALIACAO_RE.search(body_text)
        if m_av:
            try:
                loader.add_value("market_value", str(_brl_to_decimal(m_av.group(1))))
            except Exception:
                pass

        # Data: DD/MM/YYYY HH:MM
        m_dt = re.search(r"(\d{2}/\d{2}/\d{4})[^,<]{0,15}(\d{2}:\d{2})", body_text)
        if m_dt:
            loader.add_value("second_auction_date", f"{m_dt.group(1)} {m_dt.group(2)}")
            loader.add_value("auction_phase", "2a_praca")

        # Endereço — "em CIDADE/UF" no título
        m_cuf = re.search(r"\b([A-ZÀ-Ú][A-Za-zÀ-ú\s.'-]{2,40}?)\s*[/-]\s*([A-Z]{2})\b",
                          h1 or og_title)
        if m_cuf:
            loader.add_value("address", {
                "raw_text": (h1 or og_title)[:300],
                "municipality_name": m_cuf.group(1).strip(),
                "uf": m_cuf.group(2).upper(),
            })

        # Imagens — galeria WooCommerce
        img_urls = response.css(
            "div.woocommerce-product-gallery img::attr(src), "
            "div.woocommerce-product-gallery img::attr(data-src), "
            "a[data-large_image]::attr(data-large_image), "
            "div.images img::attr(src)"
        ).getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            if not u or "placeholder" in u.lower():
                continue
            absolute = response.urljoin(u)
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs)

        # Documentos
        docs: list[dict] = []
        seen_doc_urls: set[str] = set()
        for a in response.css("a[href$='.pdf']"):
            url = a.css("::attr(href)").get()
            label = _normalize_text(" ".join(a.css("*::text").getall())) or None
            if not url:
                continue
            abs_url = response.urljoin(url)
            if abs_url in seen_doc_urls:
                continue
            seen_doc_urls.add(abs_url)
            docs.append({"name": label or "documento", "url": abs_url})
        if docs:
            loader.add_value("documents", docs)

        payment_options, encumbrances = _parse_auction_clauses(body_text)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event("wp_lote_extracted", url=response.url, host=host,
                       status=item.get("status"), min_bid=item.get("minimum_bid"),
                       mkt=item.get("market_value"))
        yield item

        edital_url = _find_edital_url(item)
        if edital_url:
            yield self.make_request(
                edital_url,
                callback=self._merge_edital_clauses,
                cb_kwargs={"item_html": item},
                errback=self._on_edital_error,
                meta={"handle_httpstatus_list": [403, 404], "dont_obey_robotstxt": True},
            )

    def _on_edital_error(self, failure):
        item_html = failure.request.cb_kwargs.get("item_html")
        if item_html is not None:
            yield item_html

    def _merge_edital_clauses(self, response: scrapy.http.Response, item_html):
        if response.status >= 400:
            yield item_html
            return
        try:
            text = _pdf_to_text(response.body)
        except Exception:
            yield item_html
            return
        pdf_pay, pdf_enc = _parse_auction_clauses(text) if text else ([], [])
        if not pdf_pay and not pdf_enc:
            yield item_html
            return
        existing_pay = list(item_html.get("payment_options") or [])
        existing_enc = list(item_html.get("encumbrances") or [])
        merged_pay = _dedup_clauses(existing_pay + pdf_pay, key="kind")
        merged_enc = _dedup_clauses(existing_enc + pdf_enc, key="kind")
        if len(merged_pay) == len(existing_pay) and len(merged_enc) == len(existing_enc):
            yield item_html
            return
        new_item = item_html.copy()
        new_item["payment_options"] = merged_pay
        new_item["encumbrances"] = merged_enc
        yield new_item
