"""Spider para o SaaS Bom Valor (Bomvalor Judicial).

10 tenants em data/intermediate/site_providers.csv compartilham o
sistema BV — domínio próprio com path padronizado:
  - `/imoveis/{categoria}/{slug}-{id}` para imóveis
  - `/{slug}-{id}` para outras categorias (filtramos só /imoveis/).

Markers:
  - CDN compartilhada `d3r4ngrkezrhn6.cloudfront.net/public/{tenant_id}/`.
  - Praças: texto "OFERTA INICIAL À Vista R$ N" (1ª e 2ª praças,
    repetidas no body).
  - "Avaliação Judicial: R$ N" para market_value.
  - Status: textos como "Praça Encerrada", "Em Andamento".
  - Imagens em background-image inline (CSS) — usamos regex.

Uso:
    scrapy crawl bomvalor -a sites=1
    scrapy crawl bomvalor -a sites=all
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


# Aceita só lotes em /imoveis/... — outros (veículos, eletrônicos) ficam fora.
_LOT_HREF_RE = re.compile(r"/imoveis/[a-z0-9-]+/[a-z0-9-]+-(\d+)/?$", re.I)
_BG_IMG_RE = re.compile(
    r"background-image:\s*url\(['\"]?(https?://[^'\")]+/fotos/[^'\")]+\.(?:jpe?g|png|webp))",
    re.I,
)
_OFERTA_INICIAL_RE = re.compile(
    r"OFERTA\s+INICIAL[^R]{0,30}R\$\s*([\d.,]+)", re.I | re.S
)
_AVALIACAO_RE = re.compile(
    r"Avalia[çc][ãa]o\s*(?:Judicial)?[:\s]*R\$\s*([\d.,]+)", re.I
)
_MUNICIPIO_RE = re.compile(r"Munic[íi]pio[:\s]*([A-ZÀ-Ú][A-Za-zÀ-ú\s.'-]{2,40})", re.I)


class BomvalorSpider(ProviderSpider):
    name = "bomvalor"
    provider_slug = "bomvalor"
    auctioneer_slug = "bomvalor"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
    }

    MAX_PAGES_PER_HOST = 30

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._host_seen: dict[str, set[str]] = {}

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        seen = self._host_seen.setdefault(host, set())
        kept = 0
        for href in response.css("a[href*='/imoveis/']::attr(href)").getall():
            if not _LOT_HREF_RE.search(href):
                continue
            absolute = response.urljoin(href)
            if self.host_of(absolute) != host:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            kept += 1
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url, "host": host},
            )
        page = response.meta.get("page", 1)
        self.log_event("bv_listing_done", host=host, kept=kept, page=page)

        # Paginação: muitos tenants servem /imoveis-categoria/?p=N ou
        # similares. Tenta primeiro `?page=N`, fallback `?p=N`.
        if kept > 0 and page < self.MAX_PAGES_PER_HOST:
            base = response.url.split("?")[0]
            yield self.make_request(
                f"{base}?page={page + 1}",
                callback=self.parse,
                meta={"host": host, "page": page + 1},
            )

    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("host", self.host_of(response.url))
        og_title = response.css("meta[property='og:title']::attr(content)").get() or ""
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""
        h1 = (response.css("h1::text").get() or "").strip()
        title = h1 or og_title
        # og_title vem como "{leiloeiro} | {título}"
        if "|" in title:
            title = title.split("|", 1)[1].strip()

        body_text = _normalize_text(" ".join(response.css("body *::text").getall()))
        if not _detail_is_imovel(title, og_desc + " " + body_text[:2000]):
            self.log_event("bv_lote_dropped_non_imovel", url=response.url,
                           title=title[:80])
            return

        loader = self.new_loader(response)
        auctioneer = _extract_auctioneer(response)
        if auctioneer and auctioneer.get("full_name"):
            loader.replace_value("auctioneer", auctioneer["full_name"])
            loader.add_value("auctioneer_data", auctioneer)
        else:
            loader.replace_value("auctioneer", f"bomvalor::{host}")

        m_lot = _LOT_HREF_RE.search(response.url)
        if m_lot:
            loader.add_value("source_lot_code", m_lot.group(1))

        if title:
            loader.add_value("title", title)

        # description — geralmente em div com classe genérica; usa og_desc
        # como fallback razoável.
        desc_block = " ".join(response.css(
            "div.descricao *::text, section.descricao *::text, "
            "div[class*='descricao'] *::text"
        ).getall())
        desc = _normalize_text(desc_block)
        if not desc or len(desc) < 30:
            desc = og_desc or ""
        if desc:
            loader.add_value("description", desc[:10000])

        # status: marcadores específicos
        if re.search(r"Pra[çc]a\s+Encerrada", body_text, re.I) and \
           re.search(r"ARREMATAD[OA]\b|Lance\s+vencedor", body_text, re.I):
            status = "arrematado"
        elif re.search(r"Pra[çc]a\s+Encerrada", body_text, re.I):
            status = "desconhecido"
        elif re.search(r"\bSUSPENS[OA]\b", body_text, re.I):
            status = "suspenso"
        elif re.search(r"\bCANCELAD[OA]\b", body_text, re.I):
            status = "cancelado"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Preço: usa 2ª oferta inicial (menor) como min_bid
        oferta_matches = _OFERTA_INICIAL_RE.findall(body_text)
        if oferta_matches:
            # Pega a menor (geralmente 2ª praça)
            try:
                values = [_brl_to_decimal(v) for v in oferta_matches]
                values = [v for v in values if v and v > 0]
                if values:
                    loader.add_value("minimum_bid", str(min(values)))
            except Exception:
                pass

        m_av = _AVALIACAO_RE.search(body_text)
        if m_av:
            try:
                loader.add_value("market_value", str(_brl_to_decimal(m_av.group(1))))
            except Exception:
                pass

        # Data
        m_dt = re.search(r"(\d{1,2})\s+de\s+(\w+)\.?\s+de\s+(\d{4})[\s,]+(\d{2}:\d{2})",
                         body_text, re.I)
        if m_dt:
            month_map = {"jan": "01", "fev": "02", "mar": "03", "abr": "04",
                         "mai": "05", "jun": "06", "jul": "07", "ago": "08",
                         "set": "09", "out": "10", "nov": "11", "dez": "12"}
            mon = month_map.get(m_dt.group(2)[:3].lower())
            if mon:
                day = m_dt.group(1).zfill(2)
                year = m_dt.group(3)
                loader.add_value("second_auction_date",
                                 f"{day}/{mon}/{year} {m_dt.group(4)}")
                loader.add_value("auction_phase", "2a_praca")

        # Endereço: usa Município + dedução de UF do título
        addr: dict[str, Any] = {"raw_text": title[:300]}
        m_mun = _MUNICIPIO_RE.search(body_text)
        if m_mun:
            addr["municipality_name"] = m_mun.group(1).strip()
        # UF do título "em CIDADE/UF" ou "em CIDADE - UF"
        m_uf = re.search(r"\b([A-ZÀ-Ú][A-Za-zÀ-ú\s.'-]{2,40}?)\s*[/-]\s*([A-Z]{2})\b",
                         title)
        if m_uf:
            if not addr.get("municipality_name"):
                addr["municipality_name"] = m_uf.group(1).strip()
            addr["uf"] = m_uf.group(2)
        if any(v for v in addr.values()):
            loader.add_value("address", addr)

        # Imagens via background-image inline
        body_html = response.text
        img_urls = list(dict.fromkeys(m.group(1) for m in _BG_IMG_RE.finditer(body_html)))
        # Filtra logos
        img_urls = [u for u in img_urls if "/layout/" not in u and "/logos/" not in u]
        if img_urls:
            loader.add_value("images", img_urls)

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
        self.log_event("bv_lote_extracted", url=response.url, host=host,
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
