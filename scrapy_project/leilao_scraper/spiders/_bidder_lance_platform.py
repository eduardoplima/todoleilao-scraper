"""Base para a plataforma "bidder/lance" usada por mullerleiloes, rechleiloes
e (provavelmente) outros leiloeiros do RS.

Topologia comum:

  /lotes/{categoria}             listagem paginada (querystring `?page=N`)
                                 categoria: imovel | veiculo | rural | ...
  /item/{id}/detalhes?page=N     detalhe do item

Subclasses sobrescrevem apenas:
  - `name`             slug do spider
  - `auctioneer_slug`  slug do leiloeiro (para o item)
  - `allowed_domains`  domínio único do leiloeiro
  - `start_urls`       lista contendo `https://<dominio>/lotes/imovel`

Este módulo NÃO é importável como spider direto (prefixo `_`).
"""
from __future__ import annotations

import re

from leilao_scraper.loaders import normalize_uf

from .base import BaseAuctionSpider


PAGE_QUERY_RE = re.compile(r"[?&]page=(\d+)")
ITEM_HREF_RE = re.compile(r"/item/(\d+)/detalhes")
TITLE_LOCATION_RE = re.compile(
    r"\bem\s+([A-ZÀ-Ý][\w\s]+?)\s*/\s*([A-Z]{2})\b", re.IGNORECASE
)
DESC_LOCATION_RE = re.compile(
    r"Cidade:\s*([A-ZÀ-Ý][\w\sÀ-ÿ]+?)\s*/\s*([A-Z]{2})", re.IGNORECASE
)
ENDERECO_RE = re.compile(
    r"Endere[cç]o:\s*([^\n]+?)(?:\s+Descri[cç][aã]o:|\s+Matr[ií]cula|$)",
    re.IGNORECASE,
)
AREA_RE = re.compile(r"([\d.,]+)\s*m[²2]")


class BidderLancePlatformSpider(BaseAuctionSpider):
    """Spider abstrato — subclasses são concretas via apenas configuração."""

    requires_playwright = False

    # subclasse pode sobrescrever para fazer crawl de outras categorias
    listing_path = "/lotes/imovel"

    # ---- listing -----------------------------------------------------------

    def parse(self, response):
        """Listing → segue cada `/item/` + paginação `?page=N`."""
        seen_items: set[str] = set()
        for href in response.css("a[href*='/item/']::attr(href)").getall():
            if not ITEM_HREF_RE.search(href):
                continue
            absolute = self.absolute(response, href)
            if absolute in seen_items:
                continue
            seen_items.add(absolute)
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url},
            )

        # Paginação só na primeira chamada
        current_page_match = PAGE_QUERY_RE.search(response.url)
        if current_page_match:
            return  # já estamos numa página >= 2

        page_nums: set[int] = set()
        for href in response.css("a::attr(href)").getall():
            if self.listing_path not in (href or ""):
                continue
            m = PAGE_QUERY_RE.search(href)
            if m:
                page_nums.add(int(m.group(1)))
        if not page_nums:
            return
        max_page = max(page_nums)
        self.log_event(
            "listing_paginated",
            listing=response.url, lotes_pagina_1=len(seen_items), total_paginas=max_page,
        )
        base = response.url.split("?")[0]
        for n in range(2, max_page + 1):
            sep = "&" if "?" in base or "tipo=" in response.url else "?"
            yield self.make_request(
                f"{base}?tipo=imovel&page={n}",
                callback=self.parse,
            )

    # ---- detail ------------------------------------------------------------

    def parse_property(self, response):
        loader = self.new_loader(response)

        # title — "DESCRIÇÃO EM CIDADE/UF - Lote N (ID X) :: <Site>"
        raw_title = (response.css("title::text").get() or "").strip()
        title = raw_title.split("::")[0].strip() if "::" in raw_title else raw_title
        loader.add_value("title", title)
        loader.add_value("property_type", title)

        # bloco descritivo (.text-justify contendo "Descrição:" ou "Comitente:")
        description = ""
        for el in response.css(".text-justify"):
            txt = " ".join(el.css("::text").getall())
            txt = " ".join(txt.split())
            if any(k in txt for k in ("Descri", "Comitente:", "Endereço:")):
                description = txt
                break
        if description:
            loader.add_value("description", description[:4000])
            loader.add_value("property_type", description)

        # preços — múltiplos labels possíveis (Valor de Avaliação, Lance Inicial)
        body_text = " ".join(response.css("body *::text").getall())
        body_text = " ".join(body_text.split())
        avaliacao = self.first_match(
            r"Valor\s+de\s+Avalia[cç][aã]o:?\s*(R\$\s*[\d.,]+)", body_text
        ) or self.first_match(
            r"Avalia[cç][aã]o:?\s*(R\$\s*[\d.,]+)", body_text
        )
        # 1ª praça é o primeiro "Lance Inicial" (também aceita "Mínimo:" sem
        # rótulo "Lance" — usado por cassianoleiloes p.ex.).
        lance_match = re.search(
            r"Lance\s+Inicial:?\s*(R\$\s*[\d.,]+)", body_text, re.IGNORECASE
        ) or re.search(
            r"M[íi]nimo:\s*(R\$\s*[\d.,]+)", body_text, re.IGNORECASE
        )
        if avaliacao:
            loader.add_value("market_value", avaliacao)
        if lance_match:
            loader.add_value("minimum_bid", lance_match.group(1))

        # endereço + UF — preferir DESC_LOCATION (Cidade: X/UF), depois title
        m = DESC_LOCATION_RE.search(description) if description else None
        if not m:
            m = TITLE_LOCATION_RE.search(title)
        if m:
            city = m.group(1).strip().title()
            uf = m.group(2).upper()
            street_match = ENDERECO_RE.search(description) if description else None
            street = street_match.group(1).strip().rstrip(",.") if street_match else ""
            loader.add_value("address", {
                "street": street[:240],
                "number": "",
                "complement": "",
                "neighborhood": "",
                "city": city,
                "state": normalize_uf(uf),
                "zip": "",
            })

        # áreas — primeira ocorrência de "X m²" na descrição
        if description:
            areas = AREA_RE.findall(description)
            if areas:
                loader.add_value("total_area_sqm", areas[0])

        # imagens — exclui assets do site
        seen_imgs: set[str] = set()
        images: list[str] = []
        EXCLUDED = ("logo-header", "logo-footer", "logomarca", "/banner", "icone", "favicon")
        for src in response.css("img::attr(src), img::attr(data-src)").getall():
            if not src:
                continue
            src_low = src.lower()
            if any(bad in src_low for bad in EXCLUDED):
                continue
            if not any(ext in src_low for ext in (".jpg", ".jpeg", ".png", ".webp")):
                continue
            absolute = self.absolute(response, src)
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            images.append(absolute)
        if images:
            loader.add_value("images", images)

        loader.add_value("scraped_at", self.now_iso())
        yield loader.load_item()
