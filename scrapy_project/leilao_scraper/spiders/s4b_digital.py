"""Spider para tenants do provider S4B Digital / Superbid.

Plataforma SaaS multi-tenant operada pela S4B Digital. 43 tenants em
data/intermediate/site_providers.csv. Cada tenant é um `storeId` no
backend Superbid (portalId=[2,15]).

Recon: specs/_providers/s4b_digital/.

Particularidade:
  - siteconfigprod.superbid.net/{host}/style.config.json devolve
    Cloudflare "managed challenge" mesmo com Origin/UA realistas;
    nem cURL nem Playwright headless conseguem resolver direto.
  - MAS quando o JS do próprio tenant SPA faz a request, Cloudflare
    libera (o site é cliente CF — o challenge não dispara para
    requisições XHR originárias do mesmo proprietário).
  - Solução: Playwright navega para a home do tenant; um response
    handler intercepta a resposta de siteconfigprod e captura storeId.
    Daí em diante usamos Scrapy normal para offer-query (não tem CF).

Limitações:
  - Histórico individual de bids requer JWT (api.s4bdigital.net retorna
    401). Apenas agregado é exposto.
  - Documentos do edital ficam null na resposta pública.
  - market_value não é publicado (reservedPrice ≈ initialBidValue).

Uso:
    scrapy crawl s4b_digital -a sites=1
    scrapy crawl s4b_digital -a sites=all
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import urlencode

import scrapy
from scrapy_playwright.page import PageMethod

from leilao_scraper.spiders._common_ua import BROWSER_USER_AGENT
from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders._playwright_settings import PLAYWRIGHT_CUSTOM_SETTINGS
from leilao_scraper.spiders.soleon import (
    _detail_is_imovel,
    _normalize_text,
    _parse_auction_clauses,
)


_OFFER_QUERY = "https://offer-query.superbid.net/offers/"
_SITE_CONFIG = "https://siteconfigprod.superbid.net/{host}/style.config.json"
_PHOTO_BASE = "https://ms.sbwebservices.net/photos/"

_SUBCATEGORY_TO_KIND_HINT = {
    "apartamento": "apartamento",
    "casa": "casa",
    "terreno": "terreno",
    "lote": "terreno",
    "fazenda": "rural",
    "sítio": "rural",
    "sitio": "rural",
    "chácara": "rural",
    "comercial": "comercial",
    "galpão": "comercial",
    "galpao": "comercial",
    "prédio": "comercial",
    "predio": "comercial",
}


class S4BDigitalSpider(ProviderSpider):
    name = "s4b_digital"
    provider_slug = "s4b_digital"
    auctioneer_slug = "s4b_digital"
    requires_playwright = True

    custom_settings = {
        **PLAYWRIGHT_CUSTOM_SETTINGS,
        # Playwright só na home do tenant — depois cai pra HTTP normal.
        # Concorrência baixa porque cada home consome ~5s de browser.
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 0.5,
        "PLAYWRIGHT_MAX_PAGES_PER_CONTEXT": 4,
    }

    PAGE_SIZE = 30
    # Cap defensivo
    MAX_PAGES_PER_STORE = 60

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # host → {storeId, portalId}; preenchido via response handler
        self._store_map: dict[str, dict] = {}

    def start_requests(self) -> Iterable[Any]:
        self._open_incremental_db()
        yield from super().start_requests()

    def closed(self, reason: str) -> None:
        self.close_incremental_db()

    # ------------------------------------------------------------------
    # Nível 1: home do tenant via Playwright (intercepta siteconfigprod)
    # ------------------------------------------------------------------
    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url).lower()
        # Mesmo recurso, agora via Playwright pra disparar o XHR interno
        # do SPA que carrega siteconfigprod (libera CF).
        target_url = f"https://{host}/?searchType=opened&productTypeId=13"
        yield self.make_request(
            target_url,
            callback=self.parse_tenant_home,
            meta={
                "host": host,
                "playwright": True,
                "playwright_include_page": True,
                "playwright_page_event_handlers": {
                    "response": self._capture_siteconfig,
                },
                "playwright_page_methods": [
                    PageMethod("wait_for_load_state", "networkidle"),
                    # Pequena pausa pra garantir que o XHR siteconfigprod
                    # já foi disparado e completou.
                    PageMethod("wait_for_timeout", 2000),
                ],
            },
            dont_filter=True,
        )

    async def _capture_siteconfig(self, response):
        """Handler registrado no `page.on('response', ...)`.
        Captura a resposta de siteconfigprod/style.config.json e popula
        self._store_map[host]."""
        url = response.url
        if "siteconfigprod" not in url or "style.config.json" not in url:
            return
        m = re.search(r"siteconfigprod[^/]+/([^/]+)/style\.config\.json", url)
        if not m:
            return
        host_no_www = m.group(1)
        try:
            body = await response.body()
        except Exception as e:
            self.logger.warning(f"_capture_siteconfig body read failed: {e}")
            return
        try:
            data = json.loads(body)
        except Exception as e:
            self.logger.warning(f"_capture_siteconfig json parse failed for {host_no_www}: {e}; preview={body[:100]!r}")
            return
        store_id = data.get("storeId") or (data.get("store") or {}).get("id")
        portal_id = data.get("portalId") or 2
        if not store_id:
            return
        self._store_map[host_no_www] = {"storeId": store_id, "portalId": portal_id}
        self._store_map[f"www.{host_no_www}"] = {"storeId": store_id, "portalId": portal_id}
        self.logger.info(f"_capture_siteconfig OK: {host_no_www} → storeId={store_id} portalId={portal_id}")

    async def parse_tenant_home(self, response: scrapy.http.Response):
        host = response.meta["host"]
        page = response.meta.get("playwright_page")
        if page is not None:
            await page.close()
        cfg = self._store_map.get(host) or self._store_map.get(host[4:] if host.startswith("www.") else f"www.{host}")
        if not cfg:
            self.logger.warning(f"siteconfig not captured for {host} — skipping tenant")
            return
        self.log_event("s4b_config_done", host=host, store_id=cfg["storeId"],
                       portal_id=cfg["portalId"])
        for req in self._request_offers(
            host=host,
            store_id=cfg["storeId"],
            portal_id=cfg["portalId"],
            page=1,
        ):
            yield req

    def _request_offers(
        self, host: str, store_id: int, portal_id, page: int
    ) -> Iterable[scrapy.Request]:
        # portalId pode ser int ou [int,int] (cluster Superbid)
        portal_str = (
            f"[{','.join(str(p) for p in portal_id)}]"
            if isinstance(portal_id, (list, tuple))
            else str(portal_id)
        )
        params = {
            "filter": f"stores.id:{store_id};product.productType.id:13",
            "searchType": "opened",
            "pageNumber": str(page),
            "pageSize": str(self.PAGE_SIZE),
            "portalId": portal_str,
            "requestOrigin": "store",
            "locale": "pt_BR",
            "orderBy": "endDate:asc",
        }
        api_url = _OFFER_QUERY + "?" + urlencode(params, safe=":;,[]")
        # offer-query.superbid.net aceita Scrapy direto (sem CF challenge
        # quando o Origin é do tenant). Opt-out explícito de Playwright.
        yield scrapy.Request(
            api_url,
            callback=self.parse_offers,
            meta={
                "host": host,
                "store_id": store_id,
                "portal_id": portal_id,
                "page": page,
                "playwright": False,
            },
            headers={
                "Accept": "application/json",
                "Origin": f"https://{host}",
                "Referer": f"https://{host}/",
                "User-Agent": BROWSER_USER_AGENT,
            },
        )

    # ------------------------------------------------------------------
    # Nível 2: API offers → emite item direto
    # ------------------------------------------------------------------
    def parse_offers(self, response: scrapy.http.Response) -> Iterable[Any]:
        host = response.meta["host"]
        page = response.meta["page"]
        try:
            data = json.loads(response.text)
        except Exception as e:
            self.logger.warning(f"offers JSON parse failed: {e}")
            return

        offers = data.get("offers") or []
        total = data.get("total") or 0
        self.log_event(
            "s4b_offers_done",
            host=host,
            page=page,
            count=len(offers),
            total=total,
        )

        for offer in offers:
            offer_id = offer.get("id")
            if offer_id and self.lot_exists(host, str(offer_id)):
                product = offer.get("product") or {}
                short_desc = product.get("shortDesc") or ""
                slug_part = _slugify(short_desc)
                detail_url = f"https://{host}/oferta/{slug_part}-{offer_id}"
                status_val = None
                if offer.get("closed") or offer.get("sold"):
                    status_val = "arrematado" if (offer.get("winnerBid") or {}).get("currentWinner") else "desconhecido"
                elif (offer.get("auction") or {}).get("allOffersOfThisAuctionIsClosed"):
                    status_val = "desconhecido"
                else:
                    status_val = "aberto"
                yield self.make_listing_only_item(
                    url=detail_url,
                    source_lot_code=str(offer_id),
                    status=status_val,
                    auctioneer=f"s4b_digital::{host}",
                )
                continue
            yield from self._emit_item(offer, host)

        if offers and len(offers) == self.PAGE_SIZE and page < self.MAX_PAGES_PER_STORE:
            yield from self._request_offers(
                host=host,
                store_id=response.meta["store_id"],
                portal_id=response.meta["portal_id"],
                page=page + 1,
            )

    def _emit_item(self, offer: dict, host: str) -> Iterable[Any]:
        offer_id = offer.get("id")
        if not offer_id:
            return

        product = offer.get("product") or {}
        offer_detail = offer.get("offerDetail") or {}
        auction = offer.get("auction") or {}
        location = product.get("location") or {}

        short_desc = product.get("shortDesc") or ""
        detailed_desc = product.get("detailedDescription") or ""
        detailed_desc_clean = _normalize_text(re.sub(r"<[^>]+>", " ", detailed_desc or ""))

        if not _detail_is_imovel(short_desc, detailed_desc_clean):
            self.log_event(
                "s4b_offer_dropped_non_imovel",
                offer_id=offer_id,
                host=host,
                short_desc=short_desc[:80],
            )
            return

        slug_part = _slugify(short_desc)
        detail_url = f"https://{host}/oferta/{slug_part}-{offer_id}"

        from leilao_scraper.items import PropertyItem
        item = PropertyItem()
        item["url"] = detail_url
        item["source_listing_url"] = f"https://{host}/?searchType=opened&productTypeId=13"
        item["source_lot_code"] = str(offer_id)
        item["auctioneer"] = f"s4b_digital::{host}"

        lot_number = offer.get("lotNumber")
        title = (f"Lote {lot_number:03d} - {short_desc}" if lot_number else short_desc).strip()
        item["title"] = title
        if lot_number:
            item["lot_number"] = str(lot_number).zfill(3)
        if detailed_desc_clean:
            item["description"] = detailed_desc_clean[:10000]

        subcategory_desc = ((product.get("subCategory") or {}).get("description") or "").lower()
        for keyword, kind in _SUBCATEGORY_TO_KIND_HINT.items():
            if keyword in subcategory_desc:
                item["property_type"] = kind
                break

        if offer.get("closed") or offer.get("sold"):
            if (offer.get("winnerBid") or {}).get("currentWinner"):
                item["status"] = "arrematado"
            else:
                item["status"] = "desconhecido"
        elif auction.get("allOffersOfThisAuctionIsClosed"):
            item["status"] = "desconhecido"
        else:
            item["status"] = "aberto"

        initial = offer_detail.get("initialBidValue")
        if initial:
            item["minimum_bid"] = str(initial)

        end_date = auction.get("endDate") or offer_detail.get("auctionEndDate")
        if end_date:
            iso = end_date.replace("Z", "")
            if "T" in iso and "+" not in iso and "-03" not in iso:
                iso = iso + "-03:00"
            item["second_auction_date"] = iso
            item["auction_phase"] = "2a_praca"

        addr = {"raw_text": _normalize_text(detailed_desc_clean[:500] or "")}
        city = location.get("city")
        uf = location.get("state")
        if city:
            # API às vezes traz "Manaus - AM" no city; isola.
            m = re.match(r"^([^-/]+?)(?:\s*[-/]\s*([A-Z]{2}))?$", city)
            if m:
                addr["municipality_name"] = m.group(1).strip()
                if m.group(2):
                    addr["uf"] = m.group(2)
        if uf and "uf" not in addr:
            # state pode vir como "Amazonas" — converte para sigla via lookup
            from leilao_scraper.spiders.soleon import _normalize_text as _n
            uf_upper = (uf or "").upper().strip()
            if len(uf_upper) == 2:
                addr["uf"] = uf_upper
            else:
                addr["uf"] = _UF_NAME_TO_CODE.get(_n(uf).lower(), None)
                if not addr["uf"]:
                    del addr["uf"]
        # Fallback de UF: location veio incompleto da API mas o slug
        # /oferta/<descricao>-<cidade>-<UF>[-<sufixo>]-<id> publica a sigla.
        # Tomamos a última sigla válida no slug (UF aparece sempre antes do
        # id numérico). municipality_name fica por conta da API/geocoder
        # porque slugs com cidades compostas e bairros intercalam tokens.
        if "uf" not in addr:
            slug = re.sub(r"^.*/oferta/", "", response.url)
            slug = re.sub(r"-\d+/?$", "", slug)
            for tok in reversed(slug.split("-")):
                if tok.upper() in {
                    "AC","AL","AM","AP","BA","CE","DF","ES","GO","MA","MG",
                    "MS","MT","PA","PB","PE","PI","PR","RJ","RN","RO","RR",
                    "RS","SC","SE","SP","TO",
                }:
                    addr["uf"] = tok.upper()
                    break
        if any(v for v in addr.values()):
            item["address"] = addr

        gallery_raw = product.get("galleryJson") or product.get("photos") or []
        photos: list[str] = []
        if isinstance(gallery_raw, str):
            try:
                gallery_raw = json.loads(gallery_raw)
            except Exception:
                gallery_raw = []
        if isinstance(gallery_raw, list):
            for entry in gallery_raw:
                if isinstance(entry, str):
                    photos.append(entry)
                elif isinstance(entry, dict):
                    url = entry.get("url") or entry.get("photoUrl") or entry.get("uuid")
                    if url:
                        if not url.startswith("http"):
                            url = _PHOTO_BASE + url + (".jpg" if "." not in url else "")
                        photos.append(url)
        if not photos:
            for uuid in (product.get("photoIds") or []):
                photos.append(_PHOTO_BASE + uuid + ".jpg")
        if photos:
            item["images"] = list(dict.fromkeys(photos))

        if detailed_desc_clean:
            payment_options, encumbrances = _parse_auction_clauses(detailed_desc_clean)
            if payment_options:
                item["payment_options"] = payment_options
            if encumbrances:
                item["encumbrances"] = encumbrances

        item["scraped_at"] = self.now_iso()

        self.log_event(
            "s4b_offer_extracted",
            offer_id=offer_id,
            host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
        )
        yield item


_UF_NAME_TO_CODE = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM",
    "bahia": "BA", "ceara": "CE", "distrito federal": "DF",
    "espirito santo": "ES", "goias": "GO", "maranhao": "MA",
    "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE",
    "piaui": "PI", "rio de janeiro": "RJ", "rio grande do norte": "RN",
    "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
    "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE",
    "tocantins": "TO",
}


def _slugify(s: str, max_len: int = 80) -> str:
    s = (s or "").lower()
    s = re.sub(
        r"[áàâãäéèêëíìîïóòôõöúùûüç]",
        lambda m: {"á":"a","à":"a","â":"a","ã":"a","ä":"a",
                   "é":"e","è":"e","ê":"e","ë":"e",
                   "í":"i","ì":"i","î":"i","ï":"i",
                   "ó":"o","ò":"o","ô":"o","õ":"o","ö":"o",
                   "ú":"u","ù":"u","û":"u","ü":"u","ç":"c"}.get(m.group(0), m.group(0)),
        s,
    )
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:max_len].rstrip("-")
