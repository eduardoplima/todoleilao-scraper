"""Spider para tenants do provider SOLEON.

SOLEON (Soluções para Leilões Online) é multi-tenant: 116 leiloeiros
brasileiros usam a mesma stack Bootstrap 4 + jQuery sobre PHP. Selectors
em `specs/_providers/soleon/selectors.yaml`.

Fluxo (3 níveis):
    1. home (= listing_active) → cards `a[href*='/leilao/'][href$='/lotes']`
    2. /leilao/{id}/lotes → cards `a[href*='/item/'][href$='/detalhes']`
    3. /item/{lot_id}/detalhes → PropertyItem

Uso:
    scrapy crawl soleon                       # 1 site (representante)
    scrapy crawl soleon -a sites=5            # top 5 SOLEON
    scrapy crawl soleon -a sites=all          # 116 sites
    scrapy crawl soleon -a urls=https://...   # URL específica
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

import scrapy

from leilao_scraper.spiders._provider_base import ProviderSpider


class SoleonSpider(ProviderSpider):
    name = "soleon"
    provider_slug = "soleon"
    auctioneer_slug = "soleon"  # placeholder; sobrescrito por host na extração
    requires_playwright = False

    custom_settings = {
        # SOLEON é estático mas tem 116 tenants — limita pra evitar tempestade
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
    }

    LEILAO_LOTES_HREF_RE = re.compile(r"/leilao/\d+/lotes/?$")
    ITEM_DETALHES_HREF_RE = re.compile(r"/item/\d+/detalhes/?$")

    # ------------------------------------------------------------------
    # Nível 1: home → /leilao/{id}/lotes
    # ------------------------------------------------------------------
    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        sel = self.selectors["listing_active"]["card_selector"]
        seen: set[str] = set()
        for href in response.css(f"{sel}::attr(href)").getall():
            if not href or not self.LEILAO_LOTES_HREF_RE.search(href):
                continue
            absolute = response.urljoin(href)
            if absolute in seen:
                continue
            seen.add(absolute)
            yield self.make_request(
                absolute,
                callback=self.parse_leilao_lotes,
                meta={"source_listing_url": response.url},
            )
        self.log_event(
            "soleon_home_done",
            host=self.host_of(response.url),
            leilao_links=len(seen),
        )

    # ------------------------------------------------------------------
    # Nível 2: /leilao/{id}/lotes → /item/{lot_id}/detalhes
    # ------------------------------------------------------------------
    def parse_leilao_lotes(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        seen: set[str] = set()
        for href in response.css("a[href*='/item/']::attr(href)").getall():
            if not href or not self.ITEM_DETALHES_HREF_RE.search(href):
                continue
            absolute = response.urljoin(href)
            if absolute in seen:
                continue
            seen.add(absolute)
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url},
            )
        self.log_event(
            "soleon_leilao_lotes_done",
            url=response.url,
            lote_links=len(seen),
        )

    # ------------------------------------------------------------------
    # Nível 3: /item/{lot_id}/detalhes → PropertyItem
    # ------------------------------------------------------------------
    def parse_property(self, response: scrapy.http.Response):
        loader = self.new_loader(response)
        # auctioneer override: usa host como discriminador entre os 116 tenants
        host = self.host_of(response.url)
        loader.replace_value("auctioneer", f"soleon::{host}")

        # title — meta description: "Lote 001 - {TÍTULO} (ID {lot_id})"
        meta_desc = (
            response.css("meta[name='description']::attr(content)").get()
            or response.css("meta[property='og:title']::attr(content)").get()
            or ""
        )
        loader.add_value("title", meta_desc)

        # status — div.label_lote class names: aberto_lance, sem_licitante,
        # vendido, sustado
        label_classes = response.css("div.label_lote::attr(class)").get() or ""
        loader.add_value("status", _map_status(label_classes))

        # price_minimum / price_market — h6 texts contendo R$
        price_min = _extract_brl_after_label(response, ["Lance Inicial", "Lance Mínimo"])
        loader.add_value("minimum_bid", price_min)
        price_market = _extract_brl_after_label(response, ["Valor de Avaliação", "Avaliação"])
        loader.add_value("market_value", price_market)

        # encerramento — h6 with date "Encerramento: DD/MM/YYYY HH:MM:SS"
        encerramento_text = _text_after_label(response, ["Encerramento", "Encerramento do Leilão"])
        if encerramento_text:
            iso = _parse_br_datetime_iso(encerramento_text)
            if iso:
                # Single-round: trata como segunda praça (judicial padrão SOLEON)
                loader.add_value("second_auction_date", iso)
                loader.add_value("auction_phase", "2a_praca")

        # description — div com "Descrição:" como heading
        desc = " ".join(response.css("div:contains('Descrição:') *::text").getall()).strip()
        if desc:
            # Limpa o "Descrição:" prefix repetido
            desc = re.sub(r"^\s*Descri[çc][aã]o:\s*", "", desc, count=1)
            loader.add_value("description", desc[:5000])

        # address — h5 "Localização do Imóvel" + irmão div
        address_text = " ".join(
            response.xpath(
                "//h5[contains(., 'Localiza')]/following-sibling::div[1]//text()"
            ).getall()
        ).strip()
        if address_text:
            loader.add_value("address", _parse_address(address_text))

        # images — CDN cloudfront ou gocache
        img_urls = response.css(
            "img[src*='cloudfront.net/bens/']::attr(src), "
            "img[src*='cdn.gocache.net/bens/']::attr(src)"
        ).getall()
        # Dedup preservando ordem
        seen: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            absolute = response.urljoin(u)
            if absolute in seen:
                continue
            seen.add(absolute)
            unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs)

        # documents — pdf links no .arquivos-lote
        docs: list[dict] = []
        for a in response.css("div.arquivos-lote a[href$='.pdf']"):
            url = a.css("::attr(href)").get()
            label = " ".join(a.css("::text").getall()).strip() or None
            if url:
                docs.append({"name": label or "documento", "url": response.urljoin(url)})
        if docs:
            loader.add_value("documents", docs)

        # bids — div.ult_body div.ultimos-lances-item (server-side)
        bids = _extract_bids(response)
        if bids:
            loader.add_value("bids", bids)

        # source_lot_code — extrai do path /item/{id}/detalhes
        m = re.search(r"/item/(\d+)/detalhes", response.url)
        if m:
            loader.add_value("source_lot_code", m.group(1))

        # scraped_at
        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "soleon_lote_extracted",
            url=response.url,
            host=host,
            status=item.get("status"),
            bids=len(item.get("bids") or []),
        )
        yield item


# ---------------------------------------------------------------------------
# Helpers locais (puro Python, fáceis de testar isoladamente)
# ---------------------------------------------------------------------------


_STATUS_MAP = {
    "aberto_lance": "aberto",
    "sem_licitante": "cancelado",  # encerrado sem arrematante
    "vendido": "arrematado",
    "sustado": "cancelado",
}


def _map_status(class_attr: str) -> str:
    classes = (class_attr or "").lower()
    for key, value in _STATUS_MAP.items():
        if key in classes:
            return value
    return "desconhecido"


_BRL_RE = re.compile(r"R\$\s*([\d.,]+)")


def _extract_brl_after_label(response, labels: list[str]) -> str | None:
    """Procura R$ NNN no texto que segue um <h6> contendo cada label."""
    for label in labels:
        text = " ".join(
            response.xpath(
                f"//h6[contains(., {label!r})]/following-sibling::*[1]//text() | "
                f"//h6[contains(., {label!r})]//text()"
            ).getall()
        )
        m = _BRL_RE.search(text)
        if m:
            try:
                return str(_brl_to_decimal(m.group(1)))
            except (InvalidOperation, ValueError):
                continue
    return None


def _text_after_label(response, labels: list[str]) -> str:
    for label in labels:
        text = " ".join(
            response.xpath(
                f"//h6[contains(., {label!r})]//text()"
            ).getall()
        ).strip()
        if text:
            return text
    return ""


def _brl_to_decimal(raw: str) -> Decimal:
    """'1.234,56' → Decimal('1234.56'). '1234' → Decimal('1234')."""
    s = raw.strip().replace(".", "").replace(",", ".")
    return Decimal(s)


_BR_DT_RE = re.compile(
    r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?"
)


def _parse_br_datetime_iso(text: str) -> str | None:
    m = _BR_DT_RE.search(text)
    if not m:
        return None
    d, mth, y, h, mi, s = m.groups()
    return f"{y}-{mth}-{d}T{h}:{mi}:{s or '00'}-03:00"


def _parse_address(raw: str) -> dict:
    """Heurística simples sobre 'Rua X, 14 - Bairro - Cidade / UF'."""
    cleaned = re.sub(r"\s+", " ", raw).strip()
    out: dict[str, Any] = {"raw_text": cleaned}
    # UF no fim: "/ XX"
    m = re.search(r"/\s*([A-Z]{2})\s*$", cleaned)
    if m:
        out["state"] = m.group(1)
    # Cidade entre " - " e "/UF"
    m = re.search(r"-\s*([^-/]+?)\s*/\s*[A-Z]{2}\s*$", cleaned)
    if m:
        out["city"] = m.group(1).strip()
    # Bairro: penúltimo segmento separado por " - "
    parts = [p.strip() for p in cleaned.split(" - ")]
    if len(parts) >= 3:
        out["neighborhood"] = parts[-2]
    # Rua + número: primeiro segmento
    if parts:
        m = re.match(r"^(.+?),\s*([\dSNs/-]+)\s*$", parts[0])
        if m:
            out["street"] = m.group(1).strip()
            out["number"] = m.group(2).strip()
        else:
            out["street"] = parts[0]
    return out


def _extract_bids(response) -> list[dict]:
    """Histórico de lances SOLEON em div.ult_body div.ultimos-lances-item."""
    bids: list[dict] = []
    for item in response.css("div.ult_body div.ultimos-lances-item"):
        valor_raw = item.css(".ult_valor_lance::text").get() or ""
        data_raw = item.css(".ult_data_lance::text").get() or ""
        usuario = (item.css(".ult_usuario_lance::text").get() or "").strip()
        m_valor = _BRL_RE.search(valor_raw)
        if not m_valor:
            continue
        try:
            value = _brl_to_decimal(m_valor.group(1))
        except (InvalidOperation, ValueError):
            continue
        ts = _parse_br_datetime_iso(data_raw)
        if not ts:
            continue
        bids.append({
            "timestamp": ts,
            "value_brl": str(value),
            "bidder_raw": usuario or None,
        })
    return bids
