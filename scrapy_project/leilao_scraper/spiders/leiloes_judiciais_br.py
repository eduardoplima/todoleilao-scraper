"""Spider para o cluster `leiloes_judiciais_br` (Vue SPA + JSON API).

Rewrite de 2026-05-14 — em algum momento desde 2026-05-01 o cluster
migrou para Vue SPA e o spider anterior (Nuxt-based, baseado em DOM
`/lote/{leilao_id}/{lot_id}`) parou de funcionar (paths quebrados).
A nova versão usa a API JSON discovered via JS bundle:

```
POST /core/api/get-lotes
Content-Type: application/json
Body: {"id_leilao": N}
→ {"items": [{lote_id, vl_lanceminimo, nm_descricao, imovel_id, ...}]}
```

E para listar leilões:

```
GET /core/api/get-leiloes?pg=1&itens_pagina=40
→ {"items": [{id, nm, dt, ...}], "totalPages": ...}
```

Esses endpoints existem em todos os sites do cluster (verificado:
joserodovalholeiloes, mariafixerleiloes, capitalvalorleiloes, etc).

Uso:
    scrapy crawl leiloes_judiciais_br -a sites=1
    scrapy crawl leiloes_judiciais_br -a sites=all
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import scrapy

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _normalize_text,
    _parse_br_datetime_iso,
)


_TYPE_MAP = {
    "apartamento": "apartamento",
    "apartamentos": "apartamento",
    "casa": "casa",
    "casas": "casa",
    "terreno": "terreno",
    "terrenos": "terreno",
    "lote": "terreno",
    "fazenda": "rural",
    "fazendas": "rural",
    "sitio": "rural",
    "chácara": "rural",
    "chacara": "rural",
    "rural": "rural",
    "loja": "comercial",
    "sala": "comercial",
    "comercial": "comercial",
    "galpão": "comercial",
}


def _classify_from_subcat(subcat: str, cat: str) -> str | None:
    s = (subcat or "").lower()
    c = (cat or "").lower()
    for key, val in _TYPE_MAP.items():
        if key in s or key in c:
            return val
    if "imove" in c or "imóve" in c:
        return "outro"
    return None


def _iso_from_api_dt(s: str | None) -> str | None:
    """API retorna '2026-05-29 16:00:00-03' → '2026-05-29T16:00:00-03:00'."""
    if not s:
        return None
    m = re.match(
        r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})\s*([+-]\d{2}):?(\d{2})?",
        s,
    )
    if m:
        y, mo, d, h, mi, se, tzh, tzm = m.groups()
        return f"{y}-{mo}-{d}T{h}:{mi}:{se}{tzh}:{tzm or '00'}"
    m2 = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})", s)
    if m2:
        return s.replace(" ", "T") + "-03:00"
    return None


class LeiloesJudiciaisBrSpider(ProviderSpider):
    name = "leiloes_judiciais_br"
    provider_slug = "leiloes_judiciais_br"
    auctioneer_slug = "leiloes_judiciais_br"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.0,
    }

    MAX_LEILAO_PAGES = 50

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_leiloes: set[str] = set()
        self._seen_lotes: set[str] = set()

    # ----- Override start_urls handling -------------------------------------
    def start_requests(self) -> Iterable[scrapy.Request]:
        for url in self.start_urls:
            host = urlparse(url).hostname or ""
            api_url = f"https://{host}/core/api/get-leiloes?pg=1&itens_pagina=40"
            yield self.make_request(
                api_url,
                callback=self.parse_leiloes_api,
                meta={
                    "broker_host": host,
                    "source_listing_url": url,
                    "page": 1,
                },
            )

    # ----- Nível 1: leilões via API -----------------------------------------
    def parse_leiloes_api(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = response.meta.get("broker_host")
        page = response.meta.get("page", 1)
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.log_event("ljb_leiloes_api_bad_json", host=host, status=response.status)
            return
        items = data.get("items") or []
        total_pages = int(data.get("totalPages") or 1)
        self.log_event("ljb_leiloes_api", host=host, page=page,
                       count=len(items), total_pages=total_pages)

        for leilao in items:
            leilao_id = str(leilao.get("id") or "")
            if not leilao_id or f"{host}:{leilao_id}" in self._seen_leiloes:
                continue
            self._seen_leiloes.add(f"{host}:{leilao_id}")
            # POST /core/api/get-lotes
            yield scrapy.Request(
                f"https://{host}/core/api/get-lotes",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"id_leilao": int(leilao_id)}),
                callback=self.parse_lotes_api,
                meta={
                    "broker_host": host,
                    "leilao_id": leilao_id,
                    "leilao_data": leilao,
                    "source_listing_url": response.meta.get("source_listing_url"),
                },
            )

        # Próxima página
        if page < total_pages and page < self.MAX_LEILAO_PAGES:
            yield self.make_request(
                f"https://{host}/core/api/get-leiloes?pg={page + 1}&itens_pagina=40",
                callback=self.parse_leiloes_api,
                meta={
                    "broker_host": host,
                    "source_listing_url": response.meta.get("source_listing_url"),
                    "page": page + 1,
                },
            )

    # ----- Nível 2: lotes do leilão via API ---------------------------------
    def parse_lotes_api(self, response: scrapy.http.Response):
        host = response.meta.get("broker_host")
        leilao = response.meta.get("leilao_data") or {}
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            return
        items = data.get("items") or []
        kept = 0
        for lote in items:
            # Filtro de imóvel: id_segmento=3 ou nm_segmento contém "imov"
            seg = (lote.get("nm_segmento") or "").lower()
            id_seg = lote.get("id_segmento")
            is_imovel = (id_seg == 3) or ("imove" in seg or "imóve" in seg)
            if not is_imovel:
                continue
            lote_id = str(lote.get("lote_id") or "")
            if not lote_id or f"{host}:{lote_id}" in self._seen_lotes:
                continue
            self._seen_lotes.add(f"{host}:{lote_id}")
            kept += 1
            yield from self._emit_item(host, leilao, lote, response.url)
        self.log_event("ljb_lotes_api", host=host,
                       leilao_id=response.meta.get("leilao_id"),
                       imoveis_kept=kept,
                       total_items=len(items))

    def _emit_item(self, host: str, leilao: dict, lote: dict, src_url: str):
        """Emite PropertyItem a partir do dict do lote da API."""
        # Construir a URL canônica (front-end) — placeholder com lote_id
        canonical_url = f"https://{host}/lote/{lote.get('leilao_id')}/{lote.get('lote_id')}"

        # Usar loader manualmente porque não há response
        from leilao_scraper.items import PropertyItem
        from leilao_scraper.loaders import PropertyLoader

        item = PropertyItem()
        loader = PropertyLoader(item=item)
        loader.add_value("url", canonical_url)
        loader.add_value("source_listing_url", src_url)

        leiloeiro_name = lote.get("nm_leiloeiro")
        if leiloeiro_name:
            loader.add_value("auctioneer", _normalize_text(leiloeiro_name))
            loader.add_value("auctioneer_data", {"full_name": _normalize_text(leiloeiro_name)})
        else:
            loader.add_value("auctioneer", f"leiloes_judiciais_br::{host}")

        loader.add_value("source_lot_code", str(lote.get("lote_id")))
        if lote.get("nu"):
            loader.add_value("lot_number", str(lote["nu"]))

        title = lote.get("nm_titulo_lote") or lote.get("nm_titulo_leilao")
        if title:
            loader.add_value("title", _normalize_text(title))

        desc_raw = lote.get("nm_descricao") or ""
        desc = re.sub(r"<[^>]+>", " ", desc_raw)
        desc = _normalize_text(desc)
        if len(desc) > 20:
            loader.add_value("description", desc[:10000])

        pt = _classify_from_subcat(lote.get("nm_subcategoria"), lote.get("nm_categoria"))
        if pt:
            loader.add_value("property_type", pt)

        # Endereço
        cidade = lote.get("nm_cidade")
        uf = lote.get("nm_estado")
        if cidade or uf:
            addr = {"municipality_name": cidade, "uf": uf}
            addr["raw_text"] = f"{cidade or ''} / {uf or ''}".strip(" /")
            loader.add_value("address", addr)

        # Status
        status_lote = lote.get("nm_statuslote") or ""
        s_low = status_lote.lower()
        if "arrematad" in s_low or "vendido" in s_low:
            status = "arrematado"
        elif "encerrad" in s_low or "fechad" in s_low or "finaliza" in s_low:
            status = "desconhecido"
        elif "suspens" in s_low:
            status = "suspenso"
        elif "cancelad" in s_low:
            status = "cancelado"
        elif "aberto" in s_low:
            status = "aberto"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Valores
        vl_min = lote.get("vl_lanceminimo")
        vl_aval = lote.get("vl_avaliacao") or lote.get("vl_lanceminimo_2praca")
        if vl_min:
            try:
                from decimal import Decimal
                loader.add_value("minimum_bid", str(Decimal(str(vl_min))))
            except Exception:
                pass
        if vl_aval:
            try:
                from decimal import Decimal
                loader.add_value("market_value", str(Decimal(str(vl_aval))))
            except Exception:
                pass

        # Data
        dt_iso = _iso_from_api_dt(lote.get("dt_fechamento"))
        if not dt_iso:
            dt_iso = _iso_from_api_dt(leilao.get("dt"))
        if dt_iso:
            loader.add_value("first_auction_date", dt_iso)
            loader.add_value("auction_phase", "unica")

        # Imagens — convenção do provider: /core/imagens/lote/{lote_id}/{nu}.jpg
        # API geralmente não traz lista de arquivos; deixamos vazio v1.

        loader.add_value("scraped_at", self.now_iso())

        result = loader.load_item()
        self.log_event(
            "ljb_lote_extracted",
            url=canonical_url,
            host=host,
            min_bid=result.get("minimum_bid"),
            status=status,
        )
        yield result

    # Parse padrão não é usado, mas precisa existir para satisfazer Scrapy.
    def parse(self, response):
        return None
