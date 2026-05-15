"""Grupo Lance (grupolance.com.br) — site PHP/Laravel single-tenant.

4 leiloeiros high. URL patterns:
- Listagem: home (`/`) tem cards de imóveis em destaque; categoria
  `/imoveis/{tipo}/{uf}/{cidade}` para filtros.
- Detalhe: `/imoveis/{tipo}/{uf}/{cidade}/{slug-id}` onde os últimos
  dígitos pós-último-hífen são o ID.
- HTML estático com todos os dados (h1, valor avaliação, lance inicial,
  praças, endereço, descrição, imagens em cdn.grupolance.com.br).
"""
from __future__ import annotations

import html
import re
from decimal import Decimal
from typing import Iterable

import scrapy

from leilao_scraper.spiders.base import BaseAuctionSpider
from leilao_scraper.spiders.soleon import _brl_to_decimal, _normalize_text


# /imoveis/{tipo}/{uf}/{cidade}/{slug}-{id}  → captura id no final
_LOTE_URL_RE = re.compile(r"/imoveis/[^/]+/([a-z]{2})/[^/]+/.+?-(\d+)/?$", re.I)

_TYPE_MAP = {
    "casas": "casa",
    "apartamentos": "apartamento",
    "terrenos": "terreno",
    "imoveis-rurais": "rural",
    "imoveis-comerciais": "comercial",
    "vagas-de-garagem": "outro",
}


class GrupoLanceSpider(BaseAuctionSpider):
    name = "grupolance"
    auctioneer_slug = "grupolance"
    requires_playwright = False

    start_urls = [
        "https://www.grupolance.com.br/imoveis",
    ]

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.0,
    }

    MAX_PAGES = 30

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_ids: set[str] = set()

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        page = response.meta.get("page", 1)
        kept = 0
        for href in response.css("a::attr(href)").getall():
            if not href:
                continue
            absolute = response.urljoin(href)
            m = _LOTE_URL_RE.search(absolute)
            if not m:
                continue
            lot_id = m.group(2)
            if lot_id in self._seen_ids:
                continue
            self._seen_ids.add(lot_id)
            kept += 1
            yield scrapy.Request(
                absolute,
                callback=self.parse_property,
                meta={
                    "source_listing_url": response.url,
                    "source_lot_code": lot_id,
                    "uf_hint": m.group(1).upper(),
                },
            )
        self.log_event("gl_listing_done", url=response.url, page=page, kept=kept)

        if kept > 0 and page < self.MAX_PAGES:
            next_path = response.css("a.next::attr(href), a[rel='next']::attr(href)").get()
            if next_path:
                yield scrapy.Request(
                    response.urljoin(next_path),
                    callback=self.parse,
                    meta={"page": page + 1},
                )

    def parse_property(self, response: scrapy.http.Response):
        page_html = html.unescape(response.text)
        body_text = " ".join(response.css("body *::text").getall())[:10000]

        h1 = (response.css("h1.display-6::text, h1::text").get() or "").strip()
        if not h1:
            return

        loader = self.new_loader(response)
        loader.replace_value("auctioneer", "grupolance")
        slc = response.meta.get("source_lot_code")
        if slc:
            loader.add_value("source_lot_code", slc)
        loader.add_value("title", _normalize_text(h1))

        # property_type via path /imoveis/{tipo}/...
        m_path = re.search(r"/imoveis/([^/]+)/", response.url)
        if m_path:
            pt = _TYPE_MAP.get(m_path.group(1).lower())
            if pt:
                loader.add_value("property_type", pt)

        # Avaliação: "Valor de avaliação ... R$ NNN,NN"
        av_m = re.search(
            r"Valor de avalia[çc][ãa]o.{0,200}?R\$\s*([\d.,]+)",
            page_html, re.I | re.S,
        )
        if av_m:
            try:
                loader.add_value("market_value", str(_brl_to_decimal(av_m.group(1))))
            except Exception:
                pass

        # Lances 1ª/2ª Praça via "Encerramento Xª praça ... R$ NNN,NN (Valor inicial)"
        prac_blocks = re.findall(
            r"Encerramento\s+([12])[ªºoa]\.?\s+[Pp]ra[çc]a.{0,300}?"
            r"<strong>\s*(\d{2}/\d{2}/\d{4})\s+[àa]s\s+(\d{2}:\d{2}).*?"
            r"R\$\s*([\d.,]+)\s+<span[^>]*>\s*\(Valor inicial\)",
            page_html, re.S,
        )
        first_min = None
        second_min = None
        for n, date, time, valor in prac_blocks:
            d, mo, y = date.split("/")
            h, mi = time.split(":")
            iso = f"{y}-{mo}-{d}T{h}:{mi}:00-03:00"
            try:
                v_dec = _brl_to_decimal(valor)
            except Exception:
                v_dec = None
            if n == "1":
                loader.add_value("first_auction_date", iso)
                if v_dec:
                    first_min = v_dec
            elif n == "2":
                loader.add_value("second_auction_date", iso)
                if v_dec:
                    second_min = v_dec

        # minimum_bid = menor
        candidates = [v for v in (first_min, second_min) if v]
        if candidates:
            loader.add_value("minimum_bid", str(min(candidates)))
        if first_min and second_min:
            loader.add_value("auction_phase", "2a_praca")
        elif first_min:
            loader.add_value("auction_phase", "1a_praca")

        # Status: "Encerrado" no badge, "Faça seu lance" → aberto
        bt_low = body_text.lower()
        if "arrematad" in bt_low:
            status = "arrematado"
        elif "encerrad" in bt_low and "encerramento" not in bt_low[:200]:
            status = "desconhecido"
        elif "cancelad" in bt_low:
            status = "cancelado"
        elif "faça seu lance" in bt_low or "habilite" in bt_low:
            status = "aberto"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Endereço: bloco antes do iframe Google Maps
        addr_m = re.search(
            r'<div[^>]*>\s*([^<]+?)\s*</div>\s*<iframe[^>]*google\.com/maps',
            page_html, re.S,
        )
        addr: dict = {}
        if addr_m:
            raw = _normalize_text(addr_m.group(1))
            addr["raw_text"] = raw
            # "Rua X, NN, Bairro, Cidade, UF"
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            if parts:
                addr["street_name"] = parts[0]
            if len(parts) >= 2 and re.match(r"^\d", parts[1]):
                addr["number"] = parts[1]
            if len(parts) >= 4:
                addr["district"] = parts[-3]
            if len(parts) >= 3:
                addr["municipality_name"] = parts[-2].strip()
            if len(parts) >= 2:
                last = parts[-1]
                if re.match(r"^[A-Z]{2}$", last):
                    addr["uf"] = last
        if not addr.get("uf"):
            uf_hint = response.meta.get("uf_hint")
            if uf_hint:
                addr["uf"] = uf_hint
        if addr:
            loader.add_value("address", addr)

        # Descrição: bloco da seção "Descrição do lote"
        desc_m = re.search(
            r'<h2[^>]*>Descri[çc][ãa]o do lote</h2>\s*(.+?)(?=<h2|<section)',
            page_html, re.S | re.I,
        )
        if desc_m:
            raw = re.sub(r"<br\s*/?>", " ", desc_m.group(1))
            raw = re.sub(r"<[^>]+>", " ", raw)
            desc = _normalize_text(raw)
            if len(desc) > 20:
                loader.add_value("description", desc[:10000])

        # Imagens: cdn.grupolance.com.br/batches/...
        imgs: list[str] = []
        seen: set[str] = set()
        for src in response.css(
            "img[src*='cdn.grupolance']::attr(src), "
            "a[href*='cdn.grupolance']::attr(href), "
            "a[data-rsbigimg]::attr(data-rsbigimg)"
        ).getall():
            if not src:
                continue
            if not src.endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue
            absolute = response.urljoin(src)
            if "_thumb" in absolute:
                continue
            if absolute not in seen:
                seen.add(absolute)
                imgs.append(absolute)
        if imgs:
            loader.add_value("images", imgs)

        # Documentos PDF
        docs: list[dict] = []
        for a in response.css("li.list-group-item a"):
            href = a.css("::attr(href)").get() or ""
            label = _normalize_text(" ".join(a.css("*::text").getall()))
            if href and href.startswith("#"):
                continue
            if not href:
                continue
            absolute = response.urljoin(href)
            docs.append({"name": label or "documento", "url": absolute})
        if docs:
            loader.add_value("documents", docs)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "gl_lote_extracted",
            url=response.url,
            min_bid=item.get("minimum_bid"),
            market=item.get("market_value"),
        )
        yield item
