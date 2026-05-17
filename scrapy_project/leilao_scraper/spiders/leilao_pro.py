"""Spider para tenants do provider Leilão Pro.

Plataforma multi-tenant Symfony+Twig+Bootstrap operada por
https://www.leilao.pro. 83 tenants em data/intermediate/site_providers.csv.

Recon arquitetural: specs/_providers/leilao_pro/.

Diferenças vs SOLEON:
  - URL canônica de listagem é `/leilao/lotes/imoveis` (categoria
    "imóveis" no path); paginação `?page=N`.
  - Card é `div.card-vertical` com link `a[href*='/lote_id/']`.
  - Detail tem histórico de lances inline em `div.lance-item`
    (server-side render via Twig); atualização realtime via Mercure
    SSE — não relevante pro snapshot.
  - listing_closed=null: lots desaparecem do índice após data de
    leilão; resultado final não publicado.

Uso:
    scrapy crawl leilao_pro                       # 1 site (representante)
    scrapy crawl leilao_pro -a sites=5
    scrapy crawl leilao_pro -a sites=all
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import scrapy

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.proprio_html_specific._common import _uf_from_url_slug
from leilao_scraper.spiders.soleon import (
    _BRL_RE,
    _brl_to_decimal,
    _card_category,
    _detail_is_imovel,
    _dedup_clauses,
    _extract_auctioneer,
    _find_edital_url,
    _normalize_text,
    _parse_auction_clauses,
    _pdf_to_text,
)


class LeilaoProSpider(ProviderSpider):
    name = "leilao_pro"
    provider_slug = "leilao_pro"
    auctioneer_slug = "leilao_pro"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
    }

    LOT_HREF_RE = re.compile(r"/lote_id/(\d+)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # cards já vistos por host — usado pra detectar fallback page=1 em loop
        self._host_seen: dict[str, set[str]] = {}

    def start_requests(self) -> Iterable[scrapy.Request]:
        self._open_incremental_db()
        yield from super().start_requests()

    def closed(self, reason: str) -> None:
        self.close_incremental_db()

    # ------------------------------------------------------------------
    # Nível 1: home → segue para /leilao/lotes/imoveis (categoria imóveis)
    # ------------------------------------------------------------------
    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        # Listagem direta de imóveis
        listing_url = response.urljoin("/leilao/lotes/imoveis")
        yield self.make_request(
            listing_url,
            callback=self.parse_listing,
            meta={"source_listing_url": listing_url, "host": host, "page": 1},
        )

    # ------------------------------------------------------------------
    # Nível 2: listagem paginada de lotes
    # ------------------------------------------------------------------
    # Cap defensivo: páginas reais por host raramente passam de ~100.
    # Sites do framework leilao_pro retornam a page=1 como fallback quando
    # page>max em vez de 404, então sem este cap o spider faz loop infinito.
    MAX_PAGES_PER_HOST = 100

    def parse_listing(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        kept = 0
        dropped = 0
        ambiguous = 0
        page_hrefs: list[str] = []
        seen: set[str] = set()
        # Set global por host para detectar fallback "todos os cards já
        # vistos em páginas anteriores" → fim da paginação.
        host = self.host_of(response.url)
        host_seen = self._host_seen.setdefault(host, set())

        for card in response.css("div.card-vertical"):
            href = card.css("a[href*='/lote_id/']::attr(href)").get()
            if not href or not self.LOT_HREF_RE.search(href):
                continue
            absolute = response.urljoin(href)
            if absolute in seen:
                continue
            seen.add(absolute)
            page_hrefs.append(absolute)
            if absolute in host_seen:
                # já visto em página anterior — não conta pra "kept" novo
                continue
            host_seen.add(absolute)
            verdict = _card_category(card)
            if verdict is False:
                dropped += 1
                continue
            if verdict is None:
                ambiguous += 1
            kept += 1
            m_lot = self.LOT_HREF_RE.search(absolute)
            lot_id = m_lot.group(1) if m_lot else None
            if lot_id and self.lot_exists(host, lot_id):
                badge_text = _normalize_text(" ".join(card.css(".badges-inline ::text").getall()))
                yield self.make_listing_only_item(
                    url=absolute,
                    source_lot_code=lot_id,
                    status=_map_status_text(badge_text),
                    auctioneer=f"leilao_pro::{host}",
                )
                continue
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url},
            )

        page = response.meta.get("page", 1)
        self.log_event(
            "lp_listing_done",
            url=response.url,
            page=page,
            kept=kept,
            dropped=dropped,
            ambiguous=ambiguous,
            total_cards=len(page_hrefs),
        )

        # Paginação: continua só se a página trouxe pelo menos 1 card novo
        # (não visto em página anterior) E não atingiu o cap defensivo.
        if (kept + ambiguous > 0) and page < self.MAX_PAGES_PER_HOST:
            next_page = page + 1
            base = response.url.split("?")[0]
            next_url = f"{base}?page={next_page}"
            yield self.make_request(
                next_url,
                callback=self.parse_listing,
                meta={**response.meta, "page": next_page},
            )
        elif page_hrefs and kept + ambiguous == 0:
            # Fallback detectado: página retornou só cards já vistos
            self.log_event(
                "lp_pagination_end",
                host=host,
                last_page=page,
                reason="all_cards_seen_before",
            )

    # ------------------------------------------------------------------
    # Nível 3: detail → PropertyItem
    # ------------------------------------------------------------------
    def parse_property(self, response: scrapy.http.Response):
        # Filtro de imóvel via og:title (existe em leilao_pro)
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""
        og_title = response.css("meta[property='og:title']::attr(content)").get() or ""
        if not og_title:
            og_title = (response.css("h4.black::text").get() or "").strip()
        if not _detail_is_imovel(og_title, og_desc):
            self.log_event(
                "lp_lote_dropped_non_imovel",
                url=response.url,
                title=og_title[:80],
            )
            return

        loader = self.new_loader(response)
        host = self.host_of(response.url)
        auctioneer = _extract_auctioneer(response)
        if auctioneer and auctioneer.get("full_name"):
            loader.replace_value("auctioneer", auctioneer["full_name"])
            loader.add_value("auctioneer_data", auctioneer)
        else:
            loader.replace_value("auctioneer", f"leilao_pro::{host}")

        # title — h4.black ou breadcrumb ativo
        title = (response.css("h4.black::text").get()
                 or response.css("ol.breadcrumb li.active::text").get()
                 or og_title or "")
        if title.strip():
            loader.add_value("title", title.strip())

        # source_lot_code do path /lote_id/{N}
        m_lot = self.LOT_HREF_RE.search(response.url)
        if m_lot:
            loader.add_value("source_lot_code", m_lot.group(1))

        # status: leilao_pro não emite badge claro pra encerrado/aberto;
        # heurística — se tem div.lance-inicial-valor visível, aberto;
        # se tem badge "ENCERRADO/CANCELADO", refletir.
        badge_text = _normalize_text(" ".join(response.css(".badges-inline ::text").getall()))
        status = _map_status_text(badge_text)
        loader.add_value("status", status)

        # minimum_bid — div.valor-preco.lance-inicial-valor
        min_bid_text = " ".join(
            response.css("div.valor-preco.lance-inicial-valor *::text, "
                         "div.valor-preco.lance-inicial-valor::text").getall()
        )
        m_min = _BRL_RE.search(min_bid_text)
        if m_min:
            try:
                loader.add_value("minimum_bid", str(_brl_to_decimal(m_min.group(1))))
            except Exception:
                pass

        # market_value — Avaliação no card-informacoes
        avalia_text = " ".join(
            response.xpath(
                "//div[contains(@class,'card-informacoes')]"
                "[.//h5[contains(., 'AVALIAÇÃO')]]"
                "//h4//text()"
            ).getall()
        )
        m_av = _BRL_RE.search(avalia_text)
        if m_av:
            try:
                loader.add_value("market_value", str(_brl_to_decimal(m_av.group(1))))
            except Exception:
                pass

        # Datas das praças — leilao_pro emite UM bloco "Data do Leilão" no
        # painel info-adicional-item. Estrutura:
        #   <h5 class="info-adicional-titulo">Data do Leilão</h5>
        #   <p class="info-adicional-valor">QUI - 21/05/2026</p>
        #   <p class="info-adicional-horario"><i .../>10h00min</p>
        # Quando há 2 praças, os preços vêm como "LANCE INICIAL 1ª DATA" /
        # "LANCE INICIAL 2ª DATA" mas a data exibida é a próxima/única.
        # Tratamos como second_auction_date (mais comum em judicial); para
        # tenants que só têm 1 praça (venda direta CAIXA), também segue
        # como scheduled_at via segunda data.
        sched_dt = _extract_leilao_pro_date(response)
        if sched_dt:
            loader.add_value("second_auction_date", sched_dt)
            loader.add_value("auction_phase", "2a_praca")

        # description — bloco accordion DESCRIÇÃO DO LOTE
        desc_nodes = response.css("div#collapseDescricao div.card-body, "
                                  "div.aviso-descricao-container ~ div.card-body")
        if desc_nodes:
            raw = " ".join(desc_nodes[0].css("*::text").getall())
            desc = _normalize_text(raw)
            if desc and len(desc) > 30:
                loader.add_value("description", desc[:10000])

        # address — derivar de descrição/breadcrumb (parser permissivo)
        # Localização frequentemente aparece como "Cidade/UF" em texto livre.
        addr_blob = (title or "") + " " + (og_desc or "")
        addr = _parse_address_loose(addr_blob)
        if addr.get("uf") or addr.get("municipality_name"):
            loader.add_value("address", addr)

        # Fallback: extrai UF do slug da URL quando o título/og_desc não
        # continha UF (ex.: "Terreno - Capão de Canoa RS" → "-rs-" no slug
        # do leilão: /leilao/justica-civel-de-capao-de-canoa-rs-06-05-2024-...).
        if not addr.get("uf"):
            uf = _uf_from_url_slug(response.url)
            if uf:
                addr["uf"] = uf
                loader.replace_value("address", addr)

        # images — /uploads/media/default/
        img_urls = response.css(
            "img[src*='/uploads/media/default/'][src*='.jpg']::attr(src), "
            "img[src*='/uploads/media/default/'][src*='.jpeg']::attr(src), "
            "img[src*='/uploads/media/default/'][src*='.png']::attr(src)"
        ).getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            absolute = response.urljoin(u)
            if absolute in seen_imgs or "/0001/60/" in absolute:  # pula logo do tenant
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs)

        # documents — PDFs em /uploads/media/documentos_*
        docs: list[dict] = []
        seen_doc_urls: set[str] = set()
        for a in response.css("a[href$='.pdf'][href*='/uploads/media/documentos_']"):
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

        # bids — server-side render
        bids = _extract_bids(response)
        if bids:
            loader.add_value("bids", bids)

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
            "lp_lote_extracted",
            url=response.url,
            host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            mkt=item.get("market_value"),
            bids=len(item.get("bids") or []),
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


# ---------------------------------------------------------------------------
# Helpers locais
# ---------------------------------------------------------------------------

_STATUS_TEXT_MAP = {
    "encerrado": "desconhecido",
    "cancelado": "cancelado",
    "suspenso": "suspenso",
    "arrematado": "arrematado",
}


def _map_status_text(text: str) -> str:
    t = (text or "").lower()
    for key, value in _STATUS_TEXT_MAP.items():
        if key in t:
            return value
    return "aberto"


_LEILAO_PRO_DATE_RE = re.compile(
    r"\b(\d{2})/(\d{2})/(\d{4})\b"
)
_LEILAO_PRO_TIME_RE = re.compile(
    # Aceita "10h00min", "10h00", "10:00", "10:00:00"
    r"(\d{1,2})\s*(?:h|:)\s*(\d{2})(?:\s*min)?"
)


def _extract_leilao_pro_date(response) -> str | None:
    """Extrai data+hora do leilão a partir do bloco info-adicional Data do Leilão.

    Retorna string 'DD/MM/YYYY HH:MM' ou None se ausente.

    Estrutura típica:
      <div class="info-adicional-item">
        <div class="info-adicional-icon">...</div>
        <div class="info-adicional-content">
          <h5 class="info-adicional-titulo">Data do Leilão</h5>
          <p class="info-adicional-valor">QUI - 21/05/2026</p>
          <p class="info-adicional-horario"><i .../>10h00min</p>
        </div>
      </div>
    """
    # XPath direto pro item com título "Data do Leilão"
    item_nodes = response.xpath(
        "//div[contains(@class,'info-adicional-item')]"
        "[.//h5[contains(., 'Data do Leil')]]"
    )
    for node in item_nodes:
        value_text = " ".join(
            node.css(".info-adicional-valor *::text, .info-adicional-valor::text").getall()
        )
        m_d = _LEILAO_PRO_DATE_RE.search(value_text)
        if not m_d:
            continue
        date_str = f"{m_d.group(1)}/{m_d.group(2)}/{m_d.group(3)}"
        time_text = " ".join(
            node.css(".info-adicional-horario *::text, .info-adicional-horario::text").getall()
        )
        m_t = _LEILAO_PRO_TIME_RE.search(time_text)
        if m_t:
            h, mi = int(m_t.group(1)), m_t.group(2)
            return f"{date_str} {h:02d}:{mi}"
        return f"{date_str} 00:00"
    return None


_ADDRESS_LOOSE_RE = re.compile(
    r"([A-ZÀ-Úa-zà-ú\s.'-]+?)\s*[/-]\s*([A-Z]{2})\b"
)


def _parse_address_loose(raw: str) -> dict:
    cleaned = _normalize_text(raw)
    out: dict[str, Any] = {"raw_text": cleaned}
    m = _ADDRESS_LOOSE_RE.search(cleaned)
    if m:
        candidate_city = m.group(1).strip().rstrip(",-").strip()
        # Filtra falsos positivos
        if 3 <= len(candidate_city) <= 50 and not re.search(r'\d', candidate_city):
            out["municipality_name"] = candidate_city
            out["uf"] = m.group(2).upper()
    return out


def _extract_bids(response) -> list[dict]:
    """Histórico de lances em div.lance-item (server-side render Mercure)."""
    bids: list[dict] = []
    for item in response.css("div.lances-list > div.lance-item"):
        # Valor principal
        valor_text = " ".join(item.css(".lance-value.valor-principal::text, "
                                       ".valor-principal *::text").getall())
        m_v = _BRL_RE.search(valor_text)
        if not m_v:
            continue
        try:
            value = _brl_to_decimal(m_v.group(1))
        except Exception:
            continue
        # Data: último .lance-info, formato 'DD/MM/YYYY | HH:MM:SS'
        info_texts = [_normalize_text(" ".join(s.css("*::text").getall()))
                      for s in item.css(".lance-info")]
        ts = None
        for t in info_texts:
            m_dt = re.search(r"(\d{2}/\d{2}/\d{4})\s*[|\s]+\s*(\d{2}:\d{2}(?::\d{2})?)", t)
            if m_dt:
                d, m_, y = m_dt.group(1).split("/")
                hms = m_dt.group(2)
                if hms.count(":") == 1:
                    hms += ":00"
                ts = f"{y}-{m_}-{d}T{hms}-03:00"
                break
        if not ts:
            continue
        # Bidder
        bidder = (item.css(".fa-user").xpath("following::text()[1]").get() or "").strip() or None
        bids.append({
            "timestamp": ts,
            "value_brl": str(value),
            "bidder_raw": bidder,
        })
    return bids
