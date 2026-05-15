"""Rico Leilões (ricoleiloes.com.br) — site Laravel/PHP single-tenant.

Comprovadamente serve 11 leiloeiros high. URL patterns:
- Listagem: `/lotes/imovel` (busca de imóveis)
- Card: `<div class="lote">` com `<a href="/item/{id}/detalhes?page=N">`
- Detalhe: `/item/{id}/detalhes` — HTML estático com:
  - `<h1>Bem Imóvel Urbano</h1>` (ou similar)
  - `#lance_inicial` com valor
  - `<b>Cidade:</b> X/UF`, `<b>Endereço:</b> Y`
  - `<b>Descrição:</b> ...`
  - Carrossel de imagens `img-cover` em `cloudfront.net/watermark/bens/`
  - Leiloeiro Oficial em bloco "LEILOEIRO OFICIAL" com JUCESP

Spider dedicado (proprio_html_specific) por simplicidade.
"""
from __future__ import annotations

import re
from typing import Iterable

import scrapy

from leilao_scraper.spiders.base import BaseAuctionSpider
from leilao_scraper.spiders.soleon import _brl_to_decimal, _normalize_text


_ITEM_HREF_RE = re.compile(r"/item/(\d+)/detalhes")

_RE_IMOVEL = re.compile(
    r"\b(im[óo]ve(?:l|is)|casa|apartamento|apto|sobrado|kitnet|"
    r"loja|sala|comercial|terreno|ch[áa]cara|fazenda|s[íi]tio|[áa]rea|rural|"
    r"galp[ãa]o|edif[íi]cio|cobertura|flat|loft)\b",
    re.I,
)

_TYPE_MAP = {
    "apartamento": "apartamento",
    "apto": "apartamento",
    "casa": "casa",
    "sobrado": "casa",
    "kitnet": "apartamento",
    "cobertura": "apartamento",
    "flat": "apartamento",
    "terreno": "terreno",
    "lote": "terreno",
    "sítio": "rural",
    "sitio": "rural",
    "fazenda": "rural",
    "chácara": "rural",
    "chacara": "rural",
    "rural": "rural",
    "loja": "comercial",
    "sala": "comercial",
    "galpão": "comercial",
    "galpao": "comercial",
    "comercial": "comercial",
    "urbano": "outro",
    "imóvel": "outro",
    "imovel": "outro",
}


def _classify(title: str) -> str | None:
    t = (title or "").lower()
    for key, val in _TYPE_MAP.items():
        if key in t:
            return val
    return None


class RicoLeiloesSpider(BaseAuctionSpider):
    name = "ricoleiloes"
    auctioneer_slug = "ricoleiloes"
    requires_playwright = False

    start_urls = [
        "https://www.ricoleiloes.com.br/lotes/imovel",
    ]

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.0,
    }

    MAX_PAGES = 30

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_items: set[str] = set()

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        page = response.meta.get("page", 1)
        kept = 0
        for href in response.css("a::attr(href)").getall():
            m = _ITEM_HREF_RE.search(href or "")
            if not m:
                continue
            item_id = m.group(1)
            if item_id in self._seen_items:
                continue
            self._seen_items.add(item_id)
            kept += 1
            absolute = response.urljoin(href)
            yield scrapy.Request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url, "source_lot_code": item_id},
            )

        self.log_event("rico_listing_done", url=response.url, page=page, kept=kept)

        if kept > 0 and page < self.MAX_PAGES:
            # Paginação
            base = re.sub(r"[?&]page=\d+", "", response.url).rstrip("?&")
            sep = "&" if "?" in base else "?"
            yield scrapy.Request(
                f"{base}{sep}page={page + 1}",
                callback=self.parse,
                meta={"page": page + 1},
            )

    def parse_property(self, response: scrapy.http.Response):
        body_text = " ".join(response.css("body *::text").getall())[:8000]

        # Title via h1 (pode haver 2 h1 — "LOTE NNN" e o tipo do bem)
        h1_list = [h.strip() for h in response.css("h1::text").getall() if h.strip()]
        title = ""
        for h in h1_list:
            if h.upper().startswith("LOTE "):
                continue
            title = h
            break
        if not title and h1_list:
            title = h1_list[0]

        if not _RE_IMOVEL.search(title) and not _RE_IMOVEL.search(body_text[:2000]):
            self.log_event("rico_dropped_non_imovel", url=response.url, title=title[:80])
            return

        loader = self.new_loader(response)
        # Leiloeiro
        leiloeiro_m = re.search(
            r"LEILOEIRO\s+OFICIAL\s*</h5>\s*([A-ZÀ-Úa-zà-ú\s.'-]+?)\s*<br\s*/?>",
            response.text, re.I,
        )
        juc_m = re.search(r"JUC([A-Z]{2})\s*(\d+)", response.text)
        if leiloeiro_m:
            name = _normalize_text(leiloeiro_m.group(1))
            loader.replace_value("auctioneer", name)
            auctioneer_data = {"full_name": name}
            if juc_m:
                auctioneer_data["juc_uf"] = juc_m.group(1)
                auctioneer_data["jucesp_number"] = juc_m.group(2)
            loader.add_value("auctioneer_data", auctioneer_data)
        else:
            loader.replace_value("auctioneer", "ricoleiloes")

        slc = response.meta.get("source_lot_code")
        if slc:
            loader.add_value("source_lot_code", slc)

        if title:
            loader.add_value("title", _normalize_text(title))

        pt = _classify(title) or _classify(body_text[:1500])
        if pt:
            loader.add_value("property_type", pt)

        # Status: heurística
        bt_low = body_text.lower()
        if "aberto para lances" in bt_low or "aceitando lances" in bt_low:
            status = "aberto"
        elif "arrematad" in bt_low:
            status = "arrematado"
        elif "encerrad" in bt_low or "lote fechado" in bt_low:
            status = "desconhecido"
        elif "cancelad" in bt_low:
            status = "cancelado"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Lance Inicial
        lance_m = re.search(
            r'id="lance_inicial"[^>]*>\s*R\$\s*([\d.,]+)',
            response.text, re.I | re.S,
        )
        if not lance_m:
            lance_m = re.search(
                r"Lance\s+Inicial\s*:?\s*</[^>]+>\s*R\$\s*([\d.,]+)",
                response.text, re.I | re.S,
            )
        if not lance_m:
            lance_m = re.search(r"Lance Inicial:\s*R\$\s*([\d.,]+)",
                                 body_text, re.I)
        if lance_m:
            try:
                loader.add_value("minimum_bid", str(_brl_to_decimal(lance_m.group(1))))
            except Exception:
                pass

        # Avaliação (não sempre exposta)
        av_m = re.search(r"Avalia[çc][ãa]o[^R]{0,40}R\$\s*([\d.,]+)",
                         body_text, re.I)
        if av_m:
            try:
                loader.add_value("market_value", str(_brl_to_decimal(av_m.group(1))))
            except Exception:
                pass

        # Data do Leilão
        data_m = re.search(
            r"Data\s+do\s+Leil[ãa]o\s*:?\s*</?[^>]+>\s*(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2})",
            response.text, re.I | re.S,
        )
        if not data_m:
            data_m = re.search(
                r"Data\s+do\s+Leil[ãa]o:\s*(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2})",
                body_text, re.I,
            )
        if data_m:
            d, m, y = data_m.group(1).split("/")
            h, mi = data_m.group(2).split(":")
            loader.add_value(
                "first_auction_date",
                f"{y}-{m}-{d}T{h.zfill(2)}:{mi}:00-03:00",
            )
            loader.add_value("auction_phase", "unica")

        # Endereço — "Cidade: X/UF", "Endereço: Y"
        cidade_m = re.search(r"Cidade:\s*</[^>]+>\s*([^<\n]+?)\s*(?:<|$)",
                             response.text, re.I)
        end_m = re.search(r"Endere[çc]o:\s*</[^>]+>\s*([^<\n]+?)\s*(?:<|$)",
                          response.text, re.I)
        addr: dict = {}
        if cidade_m:
            cidade_raw = cidade_m.group(1).strip()
            m_uf = re.match(r"^(.+?)\s*/\s*([A-Z]{2})\s*$", cidade_raw)
            if m_uf:
                addr["municipality_name"] = m_uf.group(1).strip()
                addr["uf"] = m_uf.group(2)
            else:
                addr["municipality_name"] = cidade_raw
        if end_m:
            addr["street_name"] = _normalize_text(end_m.group(1))[:200]
        if addr:
            addr["raw_text"] = (
                (addr.get("street_name") or "") + " - " +
                (addr.get("municipality_name") or "") +
                (("/" + addr["uf"]) if addr.get("uf") else "")
            ).strip(" -")
            loader.add_value("address", addr)

        # Descrição: <b>Descrição: </b>....<br/>
        desc_m = re.search(
            r"<b>Descri[çc][ãa]o:?\s*</b>\s*(.+?)(?=<(?:br|/div|p\s|h\d))",
            response.text, re.I | re.S,
        )
        if desc_m:
            raw = re.sub(r"<br\s*/?>", " ", desc_m.group(1))
            raw = re.sub(r"<[^>]+>", " ", raw)
            desc = _normalize_text(raw)
            if len(desc) > 20:
                loader.add_value("description", desc[:10000])

        # Imagens — carousel `prettyPhoto[carouselItem]` ancoradas
        imgs = response.css(
            "a[rel='prettyPhoto[carouselItem]']::attr(href)"
        ).getall()
        seen: set[str] = set()
        unique: list[str] = []
        for u in imgs:
            if u and u not in seen:
                seen.add(u)
                unique.append(u)
        if unique:
            loader.add_value("images", unique)

        # Documentos PDF
        docs: list[dict] = []
        seen_doc: set[str] = set()
        for a in response.css("a[href$='.pdf']"):
            href = a.css("::attr(href)").get() or ""
            label = _normalize_text(" ".join(a.css("*::text").getall()))
            absolute = response.urljoin(href)
            if absolute not in seen_doc:
                seen_doc.add(absolute)
                docs.append({"name": label or "documento", "url": absolute})
        if docs:
            loader.add_value("documents", docs)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "rico_lote_extracted",
            url=response.url,
            min_bid=item.get("minimum_bid"),
        )
        yield item
