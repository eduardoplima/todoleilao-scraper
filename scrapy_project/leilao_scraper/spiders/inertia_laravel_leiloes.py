r"""Spider para tenants do provider Inertia Laravel Leilões.

Plataforma multi-tenant Laravel 11 + Inertia.js (React) + Vite. ~7 tenants
identificados no INNLEI (Globo Leilões, Balbino Leilões, Sato Leilões,
Peracchi Leilões, Comprei e variantes). Identificável via:

  - `<title inertia>...</title>` (atributo `inertia` no `<title>`)
  - `<div id="app" data-page="{&quot;component&quot;:&quot;Home\/Index&quot;,...}"/>`
  - Bundles em `/build/assets/{app,inertia-vendor,react-vendor}-*.js`
  - Ziggy router carregado inline com rotas REST (api.lots.*)

Recon: specs/_providers/inertia_laravel_leiloes/.

Estratégia:
  - Skip Inertia/HTML — vamos direto aos endpoints REST que o SPA usa:
      GET /api/lots?page=N  (Laravel paginator, ~10 lots/page)
      GET /api/lots/{id}    (lot completo: images, files, values, auction,
                             address, bids, category, subcategory)
  - Esses endpoints não exigem CSRF/XSRF (anonymous, cache-friendly).
  - Cloudflare libera tudo em /api/lots (challenge dispara em /busca, mas
    o portal não precisa dessa rota).

Particularidades:
  - Globoleiloes.com.br é portal-agregador: lots em `/api/lots` têm `url`
    apontando para OUTROS tenants (balbinoleiloes etc.). Spider preserva
    o `url` original e usa o host dele como `auctioneer` slug.
  - Cada lot tem N `values` (uma praça por entrada com start/end/price).
    Mapeamos para 1ª/2ª praça quando há 2 ou mais.
  - `bids` é raramente populado publicamente (admin-only).
  - `description` vem com HTML embed (`<p>`, `<strong>`); cleanup via regex.

Uso:
    scrapy crawl inertia_laravel_leiloes -a sites=1
    scrapy crawl inertia_laravel_leiloes -a sites=all
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from urllib.parse import urlparse

import scrapy

from leilao_scraper.spiders._common_ua import BROWSER_USER_AGENT
from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _detail_is_imovel,
    _normalize_text,
    _parse_auction_clauses,
)

_BRL_DECIMAL_RE = re.compile(r"([\d.,]+)")


# Subcategoria slug → property_type vocabulário curto
_SUBCATEGORY_TO_KIND = {
    "apartamento": "apartamento",
    "casa": "casa",
    "casa-sobrado": "casa",
    "sobrado": "casa",
    "terreno": "terreno",
    "terreno-lote": "terreno",
    "lote": "terreno",
    "fazenda": "rural",
    "sitio": "rural",
    "chacara": "rural",
    "rural": "rural",
    "comercial": "comercial",
    "galpao": "comercial",
    "loja": "comercial",
    "predio-comercial": "comercial",
    "sala-escritorio": "comercial",
    "vaga-de-garagem": "outro",
    "garagem": "outro",
    "veiculo": "outro",
    "veiculos": "outro",
}


# Status da entidade Laravel (status=0 → ativo); mapeamento conservador
# baseado no que o frontend exibe ("Em andamento", "Encerrado", etc).
_API_STATUS_TO_LOT_STATUS = {
    0: "aberto",        # ativo / aceitando lances ou propostas
    1: "suspenso",
    2: "cancelado",
    3: "arrematado",
    4: "desconhecido",  # encerrado sem mais info
}


class InertiaLaravelLeiloesSpider(ProviderSpider):
    name = "inertia_laravel_leiloes"
    provider_slug = "inertia_laravel_leiloes"
    auctioneer_slug = "inertia_laravel_leiloes"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
    }

    PAGE_SIZE = 10  # Laravel paginator default
    MAX_PAGES_PER_HOST = 250

    def start_requests(self) -> Iterable[Any]:
        self._open_incremental_db()
        yield from super().start_requests()

    def closed(self, reason: str) -> None:
        self.close_incremental_db()

    # ------------------------------------------------------------------
    # Nível 1: home → /api/lots?page=1
    # ------------------------------------------------------------------
    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        yield from self._request_api_page(host, page=1, referer=response.url)

    def _request_api_page(
        self, host: str, page: int, referer: str
    ) -> Iterable[scrapy.Request]:
        api_url = f"https://{host}/api/lots?page={page}"
        yield scrapy.Request(
            api_url,
            callback=self.parse_api_lots,
            meta={"host": host, "page": page, "playwright": False},
            headers={
                "Accept": "application/json",
                "Referer": referer or f"https://{host}/leiloes",
                "User-Agent": BROWSER_USER_AGENT,
            },
            dont_filter=True,
        )

    # ------------------------------------------------------------------
    # Nível 2: /api/lots → emite request por lot OU listing-only item
    # ------------------------------------------------------------------
    def parse_api_lots(self, response: scrapy.http.Response) -> Iterable[Any]:
        host = response.meta["host"]
        page = response.meta["page"]
        try:
            data = json.loads(response.text)
        except Exception as e:
            self.logger.warning(f"api/lots JSON parse failed for {host} p{page}: {e}")
            return

        lots = data.get("data") or []
        last_page = data.get("last_page") or 1
        total = data.get("total") or 0

        self.log_event(
            "ilm_api_lots_done",
            host=host,
            page=page,
            count=len(lots),
            last_page=last_page,
            total=total,
        )

        kept = 0
        skipped = 0
        for lot in lots:
            lot_id = lot.get("id")
            if not lot_id:
                continue
            # Pre-filter pela subcategoria/título — listing lots vehículos
            # também aparece em /api/lots; queremos só imóveis.
            subcategory = (lot.get("subcategory") or {})
            subcat_type = (subcategory.get("type") or "").lower()
            subcat_slug = (subcategory.get("slug") or "").lower()
            if subcat_type and "im" not in subcat_type:
                # subcategory.type = "Veículos" / "Diversos" / "Imóveis"
                skipped += 1
                continue

            # Detail URL: prefere o `url` do API (pode apontar pra outro tenant
            # quando o site é portal-agregador como globoleiloes).
            detail_url = lot.get("url") or (
                f"https://{host}/leiloes/{lot.get('slug') or 'item'}/{lot_id}"
            )
            target_host = (urlparse(detail_url).hostname or host).lower().removeprefix("www.")

            if self.lot_exists(target_host, str(lot_id)):
                # Status do listing — usa status da entidade
                status = _API_STATUS_TO_LOT_STATUS.get(
                    lot.get("status") if isinstance(lot.get("status"), int) else None,
                    "aberto",
                )
                yield self.make_listing_only_item(
                    url=detail_url,
                    source_lot_code=str(lot_id),
                    status=status,
                    auctioneer=f"inertia_laravel_leiloes::{target_host}",
                )
                kept += 1
                continue

            # Fetch detail via API endpoint do MESMO host do `url`.
            api_detail = f"https://{target_host}/api/lots/{lot_id}"
            yield scrapy.Request(
                api_detail,
                callback=self.parse_api_lot_detail,
                meta={
                    "host": target_host,
                    "source_listing_url": f"https://{host}/leiloes",
                    "detail_url": detail_url,
                    "listing_lot": lot,
                    "playwright": False,
                },
                headers={
                    "Accept": "application/json",
                    "Referer": detail_url,
                    "User-Agent": BROWSER_USER_AGENT,
                },
                dont_filter=True,
            )
            kept += 1

        if (
            lots
            and page < last_page
            and page < self.MAX_PAGES_PER_HOST
        ):
            yield from self._request_api_page(host, page + 1, referer=response.url)

        self.log_event(
            "ilm_api_lots_page_emitted",
            host=host,
            page=page,
            kept=kept,
            skipped_non_imovel=skipped,
        )

    # ------------------------------------------------------------------
    # Nível 3: /api/lots/{id} → PropertyItem
    # ------------------------------------------------------------------
    def parse_api_lot_detail(self, response: scrapy.http.Response):
        host = response.meta["host"]
        detail_url = response.meta["detail_url"]
        try:
            lot = json.loads(response.text)
        except Exception as e:
            self.logger.warning(f"api/lots/{{id}} JSON parse failed {response.url}: {e}")
            # fallback: usa o dado do listing
            lot = response.meta.get("listing_lot") or {}

        item = self._build_item_from_api(lot, host=host, detail_url=detail_url,
                                         source_listing_url=response.meta["source_listing_url"])
        if item is None:
            return
        yield item

    # ------------------------------------------------------------------
    # Construção do PropertyItem a partir do JSON da API
    # ------------------------------------------------------------------
    def _build_item_from_api(
        self,
        lot: dict,
        *,
        host: str,
        detail_url: str,
        source_listing_url: str,
    ):
        from leilao_scraper.items import PropertyItem
        from leilao_scraper.loaders import clean_money

        lot_id = lot.get("id")
        if not lot_id:
            return None

        title = lot.get("title") or lot.get("full_title") or ""
        desc_html = lot.get("description") or ""
        desc_clean = _normalize_text(re.sub(r"<[^>]+>", " ", desc_html or ""))

        if not _detail_is_imovel(title, desc_clean):
            self.log_event(
                "ilm_lot_dropped_non_imovel",
                lot_id=lot_id,
                host=host,
                title=title[:80],
            )
            return None

        item = PropertyItem()
        item["url"] = detail_url
        item["source_listing_url"] = source_listing_url
        item["source_lot_code"] = str(lot_id)
        item["auctioneer"] = f"inertia_laravel_leiloes::{host}"
        item["title"] = title.strip()
        if desc_clean:
            item["description"] = desc_clean[:10000]

        # property_type via subcategoria
        subcat = lot.get("subcategory") or {}
        subcat_slug = (subcat.get("slug") or "").lower()
        if subcat_slug and subcat_slug in _SUBCATEGORY_TO_KIND:
            item["property_type"] = _SUBCATEGORY_TO_KIND[subcat_slug]

        # status
        api_status = lot.get("status")
        if isinstance(api_status, int):
            item["status"] = _API_STATUS_TO_LOT_STATUS.get(api_status, "aberto")
        else:
            item["status"] = "aberto"

        # Preços
        avaliation = lot.get("avaliation")
        if avaliation:
            mv = clean_money(avaliation)
            if mv is not None:
                item["market_value"] = str(mv)

        values = lot.get("values") or []
        # Min bid: a "praça vigente" não está marcada explicitamente. Usamos
        # a praça com `status` == 0 (ativa) E `end` mais próxima de hoje. Se
        # nenhuma estiver ativa, a última praça serve de baseline.
        first_dt = None
        second_dt = None
        min_price_raw = None
        if values:
            # Ordena por start cronológico
            sorted_vals = sorted(values, key=lambda v: v.get("start") or "")
            # Primeira data significativa = start da 1ª praça
            if len(sorted_vals) >= 1:
                first_dt = _iso_with_tz(sorted_vals[0].get("end") or sorted_vals[0].get("start"))
            if len(sorted_vals) >= 2:
                second_dt = _iso_with_tz(sorted_vals[1].get("end") or sorted_vals[1].get("start"))
            # min_bid: praça ativa (status=0); senão última
            active = [v for v in sorted_vals if v.get("status") == 0]
            price_source = active[0] if active else sorted_vals[-1]
            min_price_raw = price_source.get("price")

        if min_price_raw:
            mb = clean_money(min_price_raw)
            if mb is not None:
                item["minimum_bid"] = str(mb)

        if first_dt:
            item["first_auction_date"] = first_dt
        if second_dt:
            item["second_auction_date"] = second_dt
            item["auction_phase"] = "2a_praca"
        elif first_dt:
            item["auction_phase"] = "1a_praca"

        # endereço — schema rico no API
        addr: dict[str, Any] = {}
        for key, out_key in [
            ("street", "street"),
            ("number", "number"),
            ("complement", "complement"),
            ("neighborhood", "neighborhood"),
            ("city", "municipality_name"),
            ("uf", "uf"),
            ("zip_code", "cep"),
        ]:
            v = lot.get(key)
            if v:
                addr[out_key] = str(v).strip()
        # raw_text — sintetiza para o pipeline
        raw_parts = [addr.get("street"), addr.get("number"), addr.get("neighborhood"),
                     addr.get("municipality_name"), addr.get("uf")]
        raw_parts = [p for p in raw_parts if p]
        if raw_parts:
            addr["raw_text"] = ", ".join(raw_parts)[:300]
        elif lot.get("address"):
            addr["raw_text"] = str(lot["address"])[:300]
        if addr:
            item["address"] = addr

        # áreas — `sizes` é string solta tipo "859 ha" ou "120 m²"; deixa
        # para o classifier nos imóveis ou pula. Quando "m²" presente, extrai.
        sizes = lot.get("sizes") or ""
        if sizes:
            m = re.search(r"(\d+[.,]?\d*)\s*(m²|m2)", sizes, re.I)
            if m:
                try:
                    item["area_sqm"] = str(Decimal(m.group(1).replace(",", ".")))
                except (InvalidOperation, ValueError):
                    pass

        # cômodos
        if isinstance(lot.get("dormitories"), int) and lot["dormitories"] > 0:
            item["bedrooms"] = lot["dormitories"]
        if isinstance(lot.get("bathrooms"), int) and lot["bathrooms"] > 0:
            item["bathrooms"] = lot["bathrooms"]
        if isinstance(lot.get("garage_spaces"), int) and lot["garage_spaces"] > 0:
            item["parking_spots"] = lot["garage_spaces"]

        # imagens — name = UUID; CDN segue padrão /storage/...; preserva
        # apenas se o name parece arquivo. Path absoluto NÃO documentado
        # publicamente, tenant-dependent; salvamos o filename para downstream.
        img_filenames: list[str] = []
        for img in lot.get("images") or []:
            if isinstance(img, dict):
                name = img.get("name")
                if name and isinstance(name, str):
                    # Tentamos formatação CDN típica: https://{host}/storage/lots/{lot_id}/images/{name}
                    img_filenames.append(
                        f"https://{host}/storage/lots/{lot_id}/images/{name}"
                    )
        if img_filenames:
            # dedup preservando ordem
            seen: set[str] = set()
            uniq: list[str] = []
            for u in img_filenames:
                if u not in seen:
                    seen.add(u)
                    uniq.append(u)
            item["images"] = uniq

        # documentos
        docs: list[dict] = []
        for f in lot.get("files") or []:
            if not isinstance(f, dict):
                continue
            fname = f.get("file")
            label = f.get("name") or "documento"
            if not fname:
                continue
            url = f"https://{host}/storage/lots/{lot_id}/files/{fname}"
            docs.append({"name": label, "url": url})
        # Edital do auction-level
        auction = lot.get("auction") or {}
        if isinstance(auction, dict):
            notices = auction.get("notices")
            if notices and isinstance(notices, str):
                docs.append({
                    "name": "edital",
                    "url": f"https://{host}/storage/auctions/{auction.get('id')}/notices/{notices}",
                })
        if docs:
            item["documents"] = docs

        # bids — server-side, raramente populado pra público
        bids: list[dict] = []
        for b in lot.get("bids") or []:
            if not isinstance(b, dict):
                continue
            value_raw = b.get("value") or b.get("price")
            ts = b.get("created_at")
            if not value_raw or not ts:
                continue
            try:
                value = clean_money(value_raw)
            except Exception:
                continue
            if value is None:
                continue
            bids.append({
                "timestamp": _iso_with_tz(ts) or ts,
                "value_brl": str(value),
                "bidder_raw": str(b.get("user_id") or b.get("client_name") or "") or None,
            })
        if bids:
            item["bids"] = bids

        # Cláusulas — auction.rules + auction.payment_conditions + descricao
        clause_blobs: list[str] = []
        for k in ("rules", "payment_conditions"):
            v = auction.get(k) if isinstance(auction, dict) else None
            if v:
                clause_blobs.append(_normalize_text(re.sub(r"<[^>]+>", " ", v)))
        if desc_clean:
            clause_blobs.append(desc_clean)
        clause_text = " ".join(clause_blobs)
        payment_options, encumbrances = _parse_auction_clauses(clause_text)
        if payment_options:
            item["payment_options"] = payment_options
        if encumbrances:
            item["encumbrances"] = encumbrances

        item["scraped_at"] = self.now_iso()

        self.log_event(
            "ilm_lot_extracted",
            lot_id=lot_id,
            host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            mkt=item.get("market_value"),
            imgs=len(item.get("images") or []),
        )
        return item


def _iso_with_tz(value: str | None) -> str | None:
    """Normaliza '2026-04-30T19:00:00.000000Z' → '2026-04-30T19:00:00-03:00'.

    A API Laravel emite tudo em UTC com 'Z'. Convertemos para -03:00 (BR)
    sem ajustar o relógio — o Laravel já gravou em America/Sao_Paulo na
    maioria dos tenants (timezone do app.php). Quando vier ISO sem TZ,
    apenas anexa -03:00.
    """
    if not value:
        return None
    s = value.strip()
    # Remove micros e 'Z'
    s = re.sub(r"\.\d+", "", s)
    if s.endswith("Z"):
        s = s[:-1]
    # Se já tem +/- offset, mantém
    if re.search(r"[+\-]\d{2}:\d{2}$", s):
        return s
    return f"{s}-03:00"
