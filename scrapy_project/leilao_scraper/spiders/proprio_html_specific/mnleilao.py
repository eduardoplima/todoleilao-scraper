"""MN Leilão (mnleilao.com.br) — Marcus Dantas Nepomuceno (RN), Laravel.

Estrutura de URLs:
- `/busca?page=N` — listagem de leilões paginada (cards apontam para `/show/{auction_id}`)
- `/show/{auction_id}` — landing do leilão com cards de lotes (`/show/lot/{lot_id}`)
- `/show/lot/{lot_id}` — detalhe do lote: status, avaliação, lance inicial,
  data, descrição detalhada, imagens em `/storage/images/...`.

Site é HTML estático server-rendered (Laravel/Blade). Categoria por lote é
heterogênea (imóveis e veículos no mesmo leilão); filtra no detalhe via
título do lote.
"""
from __future__ import annotations

import html
import re
from decimal import InvalidOperation
from typing import Iterable

import scrapy

from leilao_scraper.spiders.base import BaseAuctionSpider
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _normalize_text,
    _parse_auction_clauses,
)


_AUCTION_HREF_RE = re.compile(r"/show/(\d+)$")
_LOT_HREF_RE = re.compile(r"/show/lot/(\d+)$")

# Categorias de imóvel (sinais positivos) e bens móveis (negativos)
_IMOVEL_RE = re.compile(
    r"\b(im[óo]vel|im[óo]veis|apartamento|apto|casa|sobrado|kitnet|"
    r"cobertura|terreno|lote|fazenda|ch[áa]cara|s[íi]tio|gleba|"
    r"sala\s+comercial|loja|galp[ãa]o|pr[ée]dio|edif[íi]cio|"
    r"resid[êe]ncial|comercial|garagem)\b",
    re.I,
)
_VEICULO_RE = re.compile(
    r"\b(autom[óo]vel|ve[íi]culo|carro|caminh[ãa]o|motocicleta|motoneta|"
    r"trator|reboque|[ôo]nibus|p[áa]tio\s+natal|placa)\b",
    re.I,
)


_TYPE_MAP = {
    "apartamento": "apartamento",
    "apto": "apartamento",
    "casa": "casa",
    "sobrado": "casa",
    "kitnet": "apartamento",
    "cobertura": "apartamento",
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
    "predio": "comercial",
    "edifício": "comercial",
    "edificio": "comercial",
    "comercial": "comercial",
}


def _classify(title: str) -> str | None:
    t = (title or "").lower()
    for key, val in _TYPE_MAP.items():
        if key in t:
            return val
    return None


class MnLeilaoSpider(BaseAuctionSpider):
    name = "mnleilao"
    auctioneer_slug = "mnleilao"
    allowed_domains = ["mnleilao.com.br"]
    requires_playwright = False

    start_urls = ["https://mnleilao.com.br/busca"]

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.0,
    }

    MAX_PAGES = 15

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_auctions: set[str] = set()
        self._seen_lots: set[str] = set()

    # ---- Nível 1: /busca paginado → /show/{auction_id} -------------------
    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        page = response.meta.get("page", 1)
        kept = 0
        for href in response.css("a::attr(href)").getall():
            if not href:
                continue
            absolute = response.urljoin(href)
            m = _AUCTION_HREF_RE.search(absolute)
            if not m:
                continue
            auction_id = m.group(1)
            if auction_id in self._seen_auctions:
                continue
            self._seen_auctions.add(auction_id)
            kept += 1
            yield scrapy.Request(
                absolute,
                callback=self.parse_auction,
                meta={"source_listing_url": response.url},
            )
        self.log_event("mn_busca_done", page=page, kept=kept)

        if kept > 0 and page < self.MAX_PAGES:
            yield scrapy.Request(
                f"https://mnleilao.com.br/busca?page={page + 1}",
                callback=self.parse,
                meta={"page": page + 1},
            )

    # ---- Nível 2: /show/{id} → /show/lot/{lot_id} -----------------------
    def parse_auction(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        body = response.text
        # Captura cláusulas gerais do leilão pro detalhe propagar.
        page_text = _normalize_text(" ".join(response.css("body *::text").getall()))
        payment_options, encumbrances = _parse_auction_clauses(page_text)

        # Data de encerramento do leilão (cabeçalho)
        # Padrão: "Encerramento às:" seguido de "DD/MM/YYYY HH:MM"
        m_end = re.search(
            r"Encerramento\s+[àa]s:\s*(\d{2}/\d{2}/\d{4})\s*(\d{1,2}:\d{2})",
            page_text, re.I,
        )
        auction_end_dt = None
        if m_end:
            auction_end_dt = f"{m_end.group(1)} {m_end.group(2)}"

        # Mapear lot_id -> título a partir dos cards <h2>LOTE N - ...</h2>
        # próximos do <a href="/show/lot/{id}">. Os cards são divs sequenciais.
        lot_titles: dict[str, str] = {}
        for card in response.css("section.leiloes div.item, .leiloes .item, .lote-item, .row > div"):
            title_h2 = card.xpath(".//h2[starts-with(normalize-space(.), 'LOTE')]/text()").get()
            if not title_h2:
                continue
            href = card.xpath(".//a[contains(@href,'/show/lot/')]/@href").get()
            if not href:
                continue
            m = _LOT_HREF_RE.search(href)
            if not m:
                continue
            lot_titles[m.group(1)] = _normalize_text(title_h2)

        # Fallback: regex no HTML cru pareando <h2>LOTE N - ...</h2> ... href="/show/lot/{id}"
        if not lot_titles:
            for m in re.finditer(
                r"<h2[^>]*>(LOTE\s+\d+[^<]+)</h2>.*?href=\"[^\"]*?/show/lot/(\d+)",
                body, re.S,
            ):
                lot_titles[m.group(2)] = _normalize_text(m.group(1))

        seen = 0
        for href in response.css("a::attr(href)").getall():
            if not href:
                continue
            absolute = response.urljoin(href)
            m = _LOT_HREF_RE.search(absolute)
            if not m:
                continue
            lot_id = m.group(1)
            if lot_id in self._seen_lots:
                continue
            self._seen_lots.add(lot_id)
            seen += 1
            yield scrapy.Request(
                absolute,
                callback=self.parse_property,
                meta={
                    "source_listing_url": response.url,
                    "source_lot_code": lot_id,
                    "lot_title": lot_titles.get(lot_id),
                    "auction_payment_options": payment_options,
                    "auction_encumbrances": encumbrances,
                    "auction_end_dt": auction_end_dt,
                },
            )
        self.log_event(
            "mn_auction_done",
            url=response.url,
            lots=seen,
            end_dt=auction_end_dt,
        )

    # ---- Nível 3: /show/lot/{lot_id} → PropertyItem ---------------------
    def parse_property(self, response: scrapy.http.Response):
        body = response.text
        body_text_full = " ".join(response.css("body *::text").getall())

        # Título do lote: vem via meta do parse_auction (mapeado dos cards
        # <h2>LOTE N - ...</h2> na página /show/{auction_id}). Fallback:
        # extrai do <h4>LOTE: LOTE N</h4> + OBJETO inline na detail page.
        title_from_meta = response.meta.get("lot_title")
        if title_from_meta:
            title_clean = title_from_meta
        else:
            m_obj = re.search(
                r"<p>\s*<strong>\s*OBJETO:\s*([^<]+?)</strong>",
                body, re.I,
            )
            if m_obj:
                title_clean = _normalize_text(html.unescape(m_obj.group(1)))
            else:
                # Último fallback: <h4>LOTE: LOTE N</h4> sozinho não vira título
                self.log_event("mn_lot_drop_no_title", url=response.url)
                return

        # Filtro categoria: imóvel passa; veículo (sem sinal de imóvel) descarta
        has_im = bool(_IMOVEL_RE.search(title_clean))
        has_ve = bool(_VEICULO_RE.search(title_clean))
        # Algumas descrições mistas (com sinal de imóvel mesmo se cita placa)
        # passam. "PÁTIO NATAL" sozinho é sucata veicular: descarta.
        if not has_im and has_ve:
            self.log_event("mn_lot_drop_veiculo", url=response.url, title=title_clean[:80])
            return
        if not has_im and not has_ve:
            # Sem sinal claro: drop pra evitar ruído.
            self.log_event("mn_lot_drop_ambiguous", url=response.url, title=title_clean[:80])
            return

        loader = self.new_loader(response)
        loader.replace_value("auctioneer", "mnleilao")
        slc = response.meta.get("source_lot_code")
        if slc:
            loader.add_value("source_lot_code", slc)
        loader.add_value("title", title_clean)

        # property_type
        pt = _classify(title_clean)
        if pt:
            loader.add_value("property_type", pt)

        # lot_number — extrai "001" de "LOTE 001 - ..."
        m_lot = re.match(r"\s*LOTE\s+(\d+)", title_clean, re.I)
        if m_lot:
            loader.add_value("lot_number", m_lot.group(1))

        # Avaliação + Lance inicial
        # <strong>Avaliação:</strong><br>R$ X,YZ
        market_value = self._extract_after_label(body, "Avaliação")
        if market_value:
            loader.add_value("market_value", market_value)
        minimum_bid = self._extract_after_label(body, "Lance inicial")
        if minimum_bid:
            loader.add_value("minimum_bid", minimum_bid)

        # Status (no <p> dentro do <li> "Status do lote")
        m_status = re.search(
            r"<strong>\s*Status\s+do\s+lote\s*:\s*</strong>\s*<br>\s*"
            r"<p[^>]*>([^<]+)</p>",
            body, re.I,
        )
        status_raw = (m_status.group(1).strip().lower() if m_status else "")
        loader.add_value("status", self._map_status(status_raw))

        # Data do lote: <strong>Data:</strong><br>DD/MM/YYYY [HH:MM]
        m_date = re.search(
            r"<strong>\s*Data\s*:\s*</strong>\s*<br>\s*"
            r"(\d{2}/\d{2}/\d{4})(?:\s*<br>\s*|\s+)(\d{1,2}:\d{2})?",
            body, re.I,
        )
        lot_date = None
        if m_date:
            d = m_date.group(1)
            t = m_date.group(2) or "00:00"
            lot_date = f"{d} {t}"
        elif response.meta.get("auction_end_dt"):
            lot_date = response.meta.get("auction_end_dt")

        if lot_date:
            # Salva como second_auction_date (encerramento) — MN não distingue
            # 1ª/2ª praça neste template; "Data" representa a data limite de
            # propostas / encerramento. Conservador.
            loader.add_value("second_auction_date", lot_date)
            loader.add_value("auction_phase", "unica")

        # Descrição: <h2>DESCRIÇÃO DETALHADA</h2> ... até próximo h2 ou section.
        m_desc = re.search(
            r"<h2[^>]*>\s*DESCRI[ÇC][ÃA]O\s+DETALHADA\s*</h2>(.+?)"
            r"(?=<h2|<section|</section>)",
            body, re.I | re.S,
        )
        if m_desc:
            raw = m_desc.group(1)
            raw = html.unescape(raw)
            raw = re.sub(r"<br\s*/?>", " ", raw)
            raw = re.sub(r"<[^>]+>", " ", raw)
            desc = _normalize_text(raw)
            if len(desc) > 20:
                loader.add_value("description", desc[:10000])

        # Imagens (carousel fotorama)
        imgs = re.findall(
            r'<img[^>]+src="(https?://mnleilao\.com\.br/storage/images/[^"]+)"',
            body,
        )
        # Dedup preservando ordem
        seen = set()
        unique_imgs = []
        for u in imgs:
            if u in seen:
                continue
            seen.add(u)
            unique_imgs.append(u)
        if unique_imgs:
            loader.add_value("images", unique_imgs)

        # Documentos PDF (edital)
        docs = []
        for href, label in re.findall(
            r'<a[^>]+href="(https?://mnleilao\.com\.br/storage/files/[^"]+\.pdf)"[^>]*>([^<]*)</a>',
            body, re.I,
        ):
            docs.append({"name": _normalize_text(label) or "edital", "url": href})
        if docs:
            loader.add_value("documents", docs)

        # Cláusulas
        payment_options = list(response.meta.get("auction_payment_options") or [])
        encumbrances = list(response.meta.get("auction_encumbrances") or [])
        detail_pay, detail_enc = _parse_auction_clauses(body_text_full)
        # Merge sem dedup elaborado: confiamos no kind unique
        seen_pay = {p["kind"] for p in payment_options}
        for p in detail_pay:
            if p["kind"] not in seen_pay:
                payment_options.append(p)
                seen_pay.add(p["kind"])
        seen_enc = {e["kind"] for e in encumbrances}
        for e in detail_enc:
            if e["kind"] not in seen_enc:
                encumbrances.append(e)
                seen_enc.add(e["kind"])
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "mn_lote_extracted",
            url=response.url,
            min_bid=item.get("minimum_bid"),
            market=item.get("market_value"),
            status=item.get("status"),
            scheduled=item.get("second_auction_date"),
        )
        yield item

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def _extract_after_label(body: str, label: str) -> str | None:
        m = re.search(
            rf"<strong>\s*{re.escape(label)}\s*:\s*</strong>\s*<br>\s*"
            r"R\$\s*([\d.,]+)",
            body, re.I,
        )
        if not m:
            return None
        try:
            return str(_brl_to_decimal(m.group(1)))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _map_status(raw: str) -> str:
        raw = (raw or "").strip().lower()
        if not raw:
            return "desconhecido"
        if "abert" in raw:
            return "aberto"
        if "arremat" in raw or "vendid" in raw:
            return "arrematado"
        if "cancelad" in raw or "sustad" in raw:
            return "cancelado"
        if "encerr" in raw:
            return "desconhecido"
        if "suspen" in raw:
            return "suspenso"
        return "desconhecido"
