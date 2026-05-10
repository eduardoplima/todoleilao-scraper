"""Spider para tenants do provider Degrau Publicidade.

Plataforma multi-tenant ASP.NET ApiEngine + jQuery SPA + SignalR.
26 tenants em data/intermediate/site_providers.csv. Cada tenant tem
seu próprio domínio mas compartilha as rotas /ApiEngine/* (Host header
+ ID_Cliente faz o roteamento server-side).

Recon: specs/_providers/degrau_publicidade/.

Particularidades:
  - Listing /busca/ é SPA hash routing (jQuery TrimPath). HTML inicial
    não tem cards.
  - API ApiEngine/GetBusca exige Antiforgery (__RVT header) E retorna
    silenciosamente vazio mesmo com Host correto — não é confiável para
    scrap multi-tenant. Trocamos para sitemap.xml (Facebook listings
    format) que toda instância Degrau publica em /sitemap.xml com
    <listing> per lot, contendo URL canônico, name, image, price BRL,
    available_dates_price_config (start/end) e address.
  - Status mapping (do bundle Ajax_Leiloes.js):
      1=Online, 2=Suspenso, 4=Encerrado, 5=Arrematado, 8=Aberto.
  - Detail page é server-side render (HTML completo) — usado pra
    description, leiloeiro, imagens completas, documentos. Preços e
    datas já vêm do sitemap.
  - Bids: POST /ApiEngine/GetLancesPropostasLote/{ID_Leilao}/{ID_Lote}
    requer __RVT. Pulado pra v1.

Uso:
    scrapy crawl degrau_publicidade -a sites=1
    scrapy crawl degrau_publicidade -a sites=all
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

import scrapy

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _BRL_RE,
    _brl_to_decimal,
    _detail_is_imovel,
    _dedup_clauses,
    _extract_auctioneer,
    _find_edital_url,
    _normalize_text,
    _parse_auction_clauses,
    _pdf_to_text,
)


# Mapping de SubStatus do ApiEngine pra core.lot_status
_SUBSTATUS_TO_LOT_STATUS = {
    1: "aberto",        # Online
    2: "suspenso",
    3: "cancelado",     # Prejudicado
    4: "desconhecido",  # Encerrado (sem arrematante explícito)
    5: "arrematado",
    6: "futuro",        # Aguardando
    7: "futuro",        # Aguardando Datas
    8: "aberto",
    9: "aberto",
    10: "cancelado",    # Condicional não realizada
    14: "aberto",       # Homologar
    15: "cancelado",
}

# Mapping de ID_Categoria_Lote → core.unit_kind. Cobertura parcial; quando
# não casa, deixa NULL e SQL classify_lot_kind preenche via description.
_CATEGORIA_TO_KIND = {
    3:  "apartamento",
    4:  "casa",
    12: "terreno_urbano",
    23: "casa",         # Sobrado
    24: "comercial",
}


class DegrauPublicidadeSpider(ProviderSpider):
    name = "degrau_publicidade"
    provider_slug = "degrau_publicidade"
    auctioneer_slug = "degrau_publicidade"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
    }

    SITEMAP_PATH = "/sitemap.xml"
    LOT_URL_RE = re.compile(r"/lote/[^/]+/(\d+)/?$")

    # ------------------------------------------------------------------
    # Nível 1: home → /sitemap.xml
    # ------------------------------------------------------------------
    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        yield self.make_request(
            response.urljoin(self.SITEMAP_PATH),
            callback=self.parse_sitemap,
            meta={"host": host},
        )

    # ------------------------------------------------------------------
    # Nível 2: parse Facebook-listings sitemap.xml
    # ------------------------------------------------------------------
    def parse_sitemap(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = response.meta["host"]
        try:
            from xml.etree import ElementTree as ET
            root = ET.fromstring(response.text)
        except Exception as e:
            self.logger.warning(f"sitemap parse failed for {host}: {e}")
            return

        listings = root.findall(".//listing")
        kept = 0
        skipped_terms = 0
        for listing in listings:
            data = _listing_to_dict(listing)
            url = data.get("url")
            if not url:
                continue
            m = self.LOT_URL_RE.search(url)
            if not m:
                continue
            # Filtro de imóvel via name (mais confiável que property_type=other)
            name = data.get("name") or ""
            description = data.get("description") or ""
            if not _detail_is_imovel(name, description + " " + name):
                skipped_terms += 1
                continue
            data["lot_id"] = m.group(1)
            yield self.make_request(
                url,
                callback=self.parse_property,
                meta={"lote_data": data, "host": host, "from_sitemap": True},
            )
            kept += 1

        self.log_event(
            "dg_sitemap_done",
            host=host,
            total_listings=len(listings),
            kept=kept,
            skipped_non_imovel=skipped_terms,
        )

    # ------------------------------------------------------------------
    # Nível 3: detail HTML — combina com lote_data do meta
    # ------------------------------------------------------------------
    def parse_property(self, response: scrapy.http.Response):
        lote_data: dict = response.meta.get("lote_data") or {}
        host = response.meta.get("host", self.host_of(response.url))

        # Filtro de imóvel — usa título + descrição
        h1 = (response.css("h1::text").get() or "").strip()
        og_title = response.css("meta[property='og:title']::attr(content)").get() or h1
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""
        sm_name = lote_data.get("name") or ""
        sm_desc = lote_data.get("description") or ""
        if not _detail_is_imovel(og_title or sm_name, og_desc + " " + sm_desc):
            self.log_event(
                "dg_lote_dropped_non_imovel",
                url=response.url,
                title=(og_title or sm_name)[:80],
            )
            return

        loader = self.new_loader(response)
        auctioneer = _extract_auctioneer(response)
        if auctioneer and auctioneer.get("full_name"):
            loader.replace_value("auctioneer", auctioneer["full_name"])
            loader.add_value("auctioneer_data", auctioneer)
        else:
            loader.replace_value("auctioneer", f"degrau_publicidade::{host}")

        # source_lot_code — extraído da URL (/lote/{slug}/{id}/)
        lot_code = lote_data.get("lot_id")
        if lot_code:
            loader.add_value("source_lot_code", str(lot_code))

        # title
        title = sm_name or h1 or og_title
        if title:
            loader.add_value("title", title.strip())

        # description — server-side
        desc = " ".join(
            response.css("section#dg-lote-descricao .dg-lote-descricao-txt *::text, "
                         "section#dg-lote-descricao *::text").getall()
        )
        desc = _normalize_text(desc)
        if not desc or len(desc) < 30:
            desc = sm_desc
            desc = _normalize_text(re.sub(r"<[^>]+>", " ", desc))
        if desc:
            loader.add_value("description", desc[:10000])

        # status: sitemap usa availability (for_sale/sold). Recon do detail
        # mostra badges mas variam por tenant — usamos availability como
        # baseline e refinamos via texto do body.
        body_blob = " ".join(response.css("body *::text").getall())[:2000].lower()
        availability = (lote_data.get("availability") or "").lower()
        if "arrematado" in body_blob or availability == "sold":
            status = "arrematado"
        elif "suspens" in body_blob:
            status = "suspenso"
        elif "cancel" in body_blob:
            status = "cancelado"
        elif availability in {"for_sale", ""}:
            status = "aberto"
        else:
            status = "desconhecido"
        loader.add_value("status", status)

        # No Facebook listings format: <price>=avaliação total, <rate>=lance
        # mínimo (taxa por interval=sale). Confirmado via amostragem em
        # gfleiloes onde rate/price ~= 0.75 (2ª praça típica).
        mkt = _parse_brl_amount(lote_data.get("price") or "")
        min_bid = _parse_brl_amount(lote_data.get("rate") or "")
        if min_bid:
            loader.add_value("minimum_bid", str(min_bid))
        if mkt and mkt != min_bid:
            loader.add_value("market_value", str(mkt))

        # data agendada — end_date do sitemap
        end_dt = lote_data.get("end_date")
        if end_dt:
            iso = end_dt
            if "T" in iso and "+" not in iso and "-03" not in iso:
                iso = iso + "-03:00"
            loader.add_value("second_auction_date", iso)
            loader.add_value("auction_phase", "2a_praca")

        # address — sitemap traz city/region (frequentemente "Acrelândia"
        # placeholder); preferimos parsear o título quando contém /UF.
        addr_raw = " ".join(filter(None, [
            lote_data.get("addr1") or "",
            lote_data.get("city") or "",
            lote_data.get("region") or "",
            lote_data.get("postal_code") or "",
        ])).strip()
        m_addr = re.search(r"\b([A-ZÀ-Ú][A-Za-zÀ-ú\s.'-]{2,40}?)\s*/\s*([A-Z]{2})\b", title)
        addr: dict = {"raw_text": addr_raw[:300] or title[:300]}
        if m_addr:
            addr["municipality_name"] = m_addr.group(1).strip()
            addr["uf"] = m_addr.group(2)
        elif lote_data.get("city"):
            addr["municipality_name"] = lote_data["city"]
        if lote_data.get("postal_code"):
            addr["cep"] = lote_data["postal_code"]
        if any(v for v in addr.values()):
            loader.add_value("address", addr)

        # images — server-side render, /imagens/{NNxNN}/
        img_urls = response.css(
            "a.jsLoteImgItem::attr(href), "
            "img[src*='/imagens/'][src*='1300']::attr(src), "
            "img[src*='/imagens/']::attr(src)"
        ).getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            if not u:
                continue
            absolute = response.urljoin(u)
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs)

        # documents — /preview/.../*.pdf
        docs: list[dict] = []
        seen_doc_urls: set[str] = set()
        for a in response.css("ul.jsLoteAnexos a[href*='/preview/'][href$='.pdf'], "
                              "a[href*='/preview/'][href$='.pdf']"):
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

        # Cláusulas
        page_text = _normalize_text(" ".join(response.css("body *::text").getall()))
        payment_options, encumbrances = _parse_auction_clauses(page_text)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "dg_lote_extracted",
            url=response.url,
            host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            mkt=item.get("market_value"),
        )
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


def _listing_to_dict(node) -> dict:
    """Achata um <listing> do Facebook-listings sitemap.xml em dict plano."""
    out: dict = {}
    for child in node:
        tag = child.tag
        if tag == "address":
            for c in child.findall("./component"):
                name = c.get("name") or ""
                if name:
                    out[name] = (c.text or "").strip()
        elif tag == "image":
            urls = [u.text for u in child.findall("./url") if u.text]
            out.setdefault("images", []).extend(urls)
        elif tag == "available_dates_price_config":
            for c in child:
                key = c.tag
                out[key] = (c.text or "").strip()
        elif tag in {"home_listing_id", "name", "availability", "description",
                     "url", "price", "property_type", "neighborhood"}:
            out[tag] = (child.text or "").strip()
    return out


def _parse_brl_amount(s: str):
    """'2163600,00 BRL' → Decimal('2163600.00'); '' → None."""
    if not s:
        return None
    m = re.match(r"\s*([\d.,]+)\s*(BRL)?", s)
    if not m:
        return None
    raw = m.group(1)
    # Formato pt-BR: pode ter '.' como milhar e ',' como decimal
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        from decimal import Decimal
        v = Decimal(raw)
        return v if v > 0 else None
    except Exception:
        return None


def _kind_to_property_type(kind: str) -> str:
    """core.unit_kind → PropertyItem.property_type vocabulary (apartamento|casa|terreno|comercial|rural|outro).

    Loader.detect_property_type bate só com vocabulário curto.
    """
    if kind in {"apartamento", "casa"}:
        return kind
    if kind.startswith("terreno"):
        return "terreno"
    if kind in {"sala_comercial", "loja", "galpao", "predio_inteiro"}:
        return "comercial"
    if kind in {"fazenda", "sitio", "chacara"}:
        return "rural"
    return "outro"
