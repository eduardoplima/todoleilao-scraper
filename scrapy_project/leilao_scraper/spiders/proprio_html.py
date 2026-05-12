"""Spider genérico best-effort para tenants `proprio_html` + SPAs diversos.

Cobre 71 sites classificados como `proprio_html` (cada site é único —
sem SaaS compartilhado) + outros providers pequenos com bloqueio
técnico (sodre_santoro, palacio_dos_leiloes, leiloesweb, etc.).

Estratégia:
  - Sempre renderiza com Playwright (SPAs e CDN-blocked sites).
  - Heurísticas universais pra descoberta de listagem e detalhe:
      1. Home renderizada → busca links que casem padrões de lote
         (/lote/{id}, /item/{id}, /produto/{slug}, /imovel/{slug}, etc.)
      2. Se home estéril, tenta `/imoveis/`, `/lotes/`, `/leiloes/`,
         `/catalogo/`, `/categoria/`, `/busca/`, `/home/`.
      3. Para cada detail page, regex sobre body text procura:
           - Avaliação, Lance Mínimo, 1º/2º Leilão, Praça
           - Cidade/UF no título ou body
           - Imagens com aspect ratio plausível
           - PDFs (edital, laudo)
  - Sem garantia de fill rate alto — é fallback pra capturar pelo menos
    URLs/títulos/preços do que for possível.

Uso:
    scrapy crawl proprio_html -a sites=1
    scrapy crawl proprio_html -a sites=all
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import scrapy
from scrapy_playwright.page import PageMethod

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _detail_is_imovel,
    _dedup_clauses,
    _extract_auctioneer,
    _find_edital_url,
    _normalize_text,
    _parse_auction_clauses,
    _pdf_to_text,
)


# Múltiplos padrões de URL de lote (regex sobre o pathname)
_LOT_PATH_PATTERNS = [
    re.compile(r"/lote[s]?/\d+"),
    re.compile(r"/item/\d+"),
    re.compile(r"/produto/[\w\-]+"),
    re.compile(r"/imovel/[\w\-]+"),
    re.compile(r"/bem/\d+"),
    re.compile(r"/externo/lote/\d+"),
    re.compile(r"/leilao/\d+/lote/\d+"),
    re.compile(r"/categoria/\d+/[^/]+/leilao/\d+/[\w\-]+"),
    re.compile(r"/oferta/[\w\-]+\-\d+"),
    re.compile(r"\?(?:cod|id)(?:lote|leilao|item)?=\d+", re.I),
]

# Paths candidatos para listagem quando home não tem lotes
_LISTING_FALLBACK_PATHS = [
    "/imoveis",
    "/categoria/imoveis",
    "/lotes",
    "/leiloes",
    "/leiloes-em-andamento",
    "/catalogo",
    "/busca",
    "/produtos",
    "/externo",
    "/externo/",
    "/home",
]

# Filtros pra descartar URLs que parecem lote mas são menu/sidebar
_LOT_URL_BLOCKLIST_RE = re.compile(
    r"/(login|cadastr|contato|quem-somos|termos|privacidad|faq|ajuda|"
    r"como-(?:participar|funciona)|alertas?|edital|blog|noticias|"
    r"vantagens|sair|logout|texto\.aspx|contato\.aspx|parceiros\.aspx|"
    r"leiloes\.aspx|leiloes_realizados\.aspx)",
    re.I,
)

_PRICE_AVALIACAO = re.compile(
    r"(?:Valor\s+(?:de\s+)?)?Avalia[çc][ãa]o(?:\s+(?:Judicial|Total))?[:\s]*"
    r"R\$\s*([\d.,]+)",
    re.I,
)
_PRICE_LANCE_MIN = re.compile(
    r"(?:Lance\s+(?:M[íi]nimo|Inicial|Atual)|Valor\s+M[íi]nimo|"
    r"Oferta\s+Inicial|Pelo\s+valor\s+de)[:\s]*R\$\s*([\d.,]+)",
    re.I,
)
_PRICE_PRACA_2 = re.compile(
    r"2[ºoº°ªa]?\s*(?:Leil[ãa]o|Pra[çc]a)[^R]{0,60}R\$\s*([\d.,]+)",
    re.I,
)
_PRICE_PRACA_1 = re.compile(
    r"1[ºoº°ªa]?\s*(?:Leil[ãa]o|Pra[çc]a)[^R]{0,60}R\$\s*([\d.,]+)",
    re.I,
)


class ProprioHtmlSpider(ProviderSpider):
    name = "proprio_html"
    provider_slug = "proprio_html"
    auctioneer_slug = "proprio_html"
    requires_playwright = True

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 1.0,
        "PLAYWRIGHT_MAX_PAGES_PER_CONTEXT": 4,
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 45_000,
    }

    MAX_LISTING_FALLBACKS = 4  # cap pra não estourar requests por host
    MAX_CATEGORIES_PER_HOST = 8  # quantas categorias seguir
    MAX_LOTS_PER_SITE = 80     # cap defensivo

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._host_state: dict[str, dict] = {}

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        state = self._host_state.setdefault(host, {
            "lot_urls_seen": set(),
            "listing_fallbacks_tried": 0,
            "category_urls_seen": set(),
            "lots_yielded": 0,
        })

        # Tenta extrair links de lote diretamente da home
        lot_links = self._extract_lot_links(response, host)
        if lot_links:
            self.log_event("ph_home_yielded", host=host, kept=len(lot_links))
            yield from self._yield_lots(lot_links, response.url, host, state)
            # Pode seguir categorias também se houver
            yield from list(self._follow_categories(response, host, state))
            return

        # Tenta seguir categorias relacionadas a imóveis
        cat_requests = list(self._follow_categories(response, host, state))
        if cat_requests:
            self.log_event("ph_categories_followed", host=host,
                           count=len(cat_requests))
            yield from cat_requests
            return

        # Home estéril — tenta paths candidatos. Continua só os primeiros 4.
        for path in _LISTING_FALLBACK_PATHS[:self.MAX_LISTING_FALLBACKS]:
            fallback_url = response.urljoin(path)
            if fallback_url == response.url:
                continue
            yield self.make_request(
                fallback_url,
                callback=self.parse_listing_fallback,
                meta={"host": host, "fallback_path": path},
                dont_filter=True,
                errback=lambda f: None,
            )

    def _follow_categories(self, response, host, state) -> Iterable[scrapy.Request]:
        """Segue links /categoria/* que parecem ser imóveis (slug contém
        'imov', 'casa', 'aparta', 'terren', 'bem')."""
        cat_hits = 0
        for href in response.css("a::attr(href)").getall():
            if not href:
                continue
            absolute = response.urljoin(href)
            if self.host_of(absolute) != host:
                continue
            if absolute in state["category_urls_seen"]:
                continue
            # Padrão: /categoria/N-slug ou /categoria/N/slug
            if not re.search(r"/categoria/\d+[\-/]", absolute):
                continue
            # Só categorias relacionadas a imóveis
            if not re.search(
                r"imo?vel|imove|casa|aparta|terren|rural|sit[ií]o|"
                r"ch[áa]cara|fazenda|comerc|gal[pl][aã]o|sala|loja",
                absolute, re.I,
            ):
                continue
            if cat_hits >= self.MAX_CATEGORIES_PER_HOST:
                break
            state["category_urls_seen"].add(absolute)
            cat_hits += 1
            yield self.make_request(
                absolute,
                callback=self.parse_listing_fallback,
                meta={"host": host, "fallback_path": "category"},
            )

    def parse_listing_fallback(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = response.meta["host"]
        state = self._host_state.setdefault(host, {
            "lot_urls_seen": set(),
            "listing_fallbacks_tried": 0,
            "lots_yielded": 0,
        })
        state["listing_fallbacks_tried"] += 1
        lot_links = self._extract_lot_links(response, host)
        self.log_event("ph_fallback_done", host=host,
                       path=response.meta["fallback_path"],
                       kept=len(lot_links))
        if lot_links:
            yield from self._yield_lots(lot_links, response.url, host, state)

    def _extract_lot_links(self, response: scrapy.http.Response, host: str) -> list[str]:
        """Inspeciona o DOM renderizado em busca de links que pareçam lotes."""
        seen: set[str] = set()
        result: list[str] = []
        for href in response.css("a::attr(href)").getall():
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            absolute = response.urljoin(href)
            if self.host_of(absolute) != host:
                continue
            if absolute in seen:
                continue
            # Drop URLs that match the blocklist (menu/footer paths)
            if _LOT_URL_BLOCKLIST_RE.search(absolute):
                continue
            # Test pattern matches
            path = absolute.split("?", 1)[0] + ("?" + absolute.split("?", 1)[1]
                                                if "?" in absolute else "")
            if any(p.search(absolute) for p in _LOT_PATH_PATTERNS):
                seen.add(absolute)
                result.append(absolute)
        return result

    def _yield_lots(self, urls: list[str], src: str, host: str,
                    state: dict) -> Iterable[scrapy.Request]:
        for url in urls:
            if url in state["lot_urls_seen"]:
                continue
            if state["lots_yielded"] >= self.MAX_LOTS_PER_SITE:
                break
            state["lot_urls_seen"].add(url)
            state["lots_yielded"] += 1
            yield self.make_request(
                url,
                callback=self.parse_property,
                meta={"source_listing_url": src, "host": host},
            )

    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("host", self.host_of(response.url))
        h1 = (response.css("h1::text").get() or "").strip()
        og_title = response.css("meta[property='og:title']::attr(content)").get() or h1
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""

        body_text = _normalize_text(" ".join(response.css("body *::text").getall()))

        if not _detail_is_imovel(og_title or h1, og_desc + " " + body_text[:3000]):
            self.log_event("ph_lote_dropped_non_imovel", url=response.url,
                           title=(og_title or h1)[:80])
            return

        loader = self.new_loader(response)
        auctioneer = _extract_auctioneer(response)
        if auctioneer and auctioneer.get("full_name"):
            loader.replace_value("auctioneer", auctioneer["full_name"])
            loader.add_value("auctioneer_data", auctioneer)
        else:
            # Subclasses específicas com `provider_slug != "proprio_html"`
            # usam o próprio slug; o genérico usa `proprio_html::host`
            # para manter rastreabilidade.
            if self.auctioneer_slug and self.auctioneer_slug != "proprio_html":
                loader.replace_value("auctioneer", self.auctioneer_slug)
            else:
                loader.replace_value("auctioneer", f"proprio_html::{host}")

        # source_lot_code — extrai N do path
        m_id = re.search(r"/(?:lote|item|bem|leilao|oferta|lot)s?/(\d+)",
                         response.url)
        if not m_id:
            m_id = re.search(r"[?&](?:cod|id)[a-z_]*=(\d+)", response.url, re.I)
        if m_id:
            loader.add_value("source_lot_code", m_id.group(1))
        else:
            # Slug fallback
            slug_match = re.search(r"/(?:produto|imovel)/([\w\-]+)/?$",
                                   response.url)
            if slug_match:
                loader.add_value("source_lot_code", slug_match.group(1))

        title = og_title or h1
        if title:
            # Vários títulos vêm como "Tenant | Subtítulo" — pega só o subtítulo
            if " | " in title:
                title = title.split(" | ", 1)[1].strip()
            loader.add_value("title", title)

        # Description
        desc_block = " ".join(response.css(
            "div.descricao *::text, "
            "div.product_description *::text, "
            "section.descricao *::text, "
            "div.entry-content *::text, "
            "div.lote-descricao *::text, "
            "div[class*='descricao'] *::text"
        ).getall())
        desc = _normalize_text(desc_block) or og_desc
        if desc:
            loader.add_value("description", desc[:10000])

        # status — div.card-status ou heurística mínima
        status_badge = (response.css(
            "div.card-status::text, .lote-status::text, .status-badge::text, "
            ".lance-status::text"
        ).get() or "").strip().lower()
        if "arrematad" in status_badge:
            status = "arrematado"
        elif "encerrad" in status_badge or "finalizad" in status_badge:
            status = "desconhecido"
        elif "suspens" in status_badge:
            status = "suspenso"
        elif "cancelad" in status_badge:
            status = "cancelado"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Preços — múltiplas heurísticas
        # 1) Avaliação para market_value
        m_av = _PRICE_AVALIACAO.search(body_text)
        if m_av:
            try:
                v = _brl_to_decimal(m_av.group(1))
                if v and v > 0:
                    loader.add_value("market_value", str(v))
            except Exception:
                pass

        # 2) minimum_bid — prefere 2ª praça (menor), fallback 1ª, fallback "Lance"
        m_min = _PRICE_PRACA_2.search(body_text)
        if not m_min:
            m_min = _PRICE_PRACA_1.search(body_text)
        if not m_min:
            m_min = _PRICE_LANCE_MIN.search(body_text)
        if m_min:
            try:
                v = _brl_to_decimal(m_min.group(1))
                if v and v > 0:
                    loader.add_value("minimum_bid", str(v))
            except Exception:
                pass

        # Datas — primeiro padrão "1ª/2ª praça: DD/MM/YYYY HH:MM"
        m_2a = re.search(
            r"2[ºoº°ªa]?\s*(?:Leil[ãa]o|Pra[çc]a)[:\s]*(\d{2}/\d{2}/\d{4})"
            r"[\s\w]{0,15}(\d{2}:\d{2})",
            body_text, re.I,
        )
        if m_2a:
            loader.add_value("second_auction_date",
                             f"{m_2a.group(1)} {m_2a.group(2)}")
            loader.add_value("auction_phase", "2a_praca")
        else:
            # Generic DD/MM/YYYY HH:MM nearby
            m_dt = re.search(r"(\d{2}/\d{2}/\d{4})[^,<]{0,10}(\d{2}:\d{2})",
                             body_text)
            if m_dt:
                loader.add_value("second_auction_date",
                                 f"{m_dt.group(1)} {m_dt.group(2)}")

        # Endereço — extrai CIDADE/UF do título ou body
        addr: dict[str, Any] = {"raw_text": title[:300] if title else ""}
        m_cuf = re.search(r"\b([A-ZÀ-Ú][A-Za-zÀ-ú\s.'-]{2,40}?)\s*[/-]\s*([A-Z]{2})\b",
                          (title or "") + " " + body_text[:500])
        if m_cuf:
            cidade = m_cuf.group(1).strip().rstrip(",.").strip()
            if 3 <= len(cidade) <= 50:
                addr["municipality_name"] = cidade
                addr["uf"] = m_cuf.group(2)
        if addr.get("municipality_name") or addr.get("raw_text"):
            loader.add_value("address", addr)

        # Imagens — filtra logos, ícones, payment badges
        img_urls = response.css("img::attr(src), img::attr(data-src)").getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            if not u or "data:image" in u:
                continue
            absolute = response.urljoin(u)
            low = absolute.lower()
            if any(skip in low for skip in (
                "logo", "favicon", "icon", "bandeira", "payment", "/styles/",
                "facebook", "instagram", "whatsapp", "twitter", "linkedin",
                "placeholder",
            )):
                continue
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        # Background-image inline (Wix-like)
        for m in re.finditer(
            r"background-image:\s*url\(['\"]?(https?://[^'\")]+\.(?:jpe?g|png|webp))",
            response.text, re.I,
        ):
            u = m.group(1)
            low = u.lower()
            if any(skip in low for skip in ("logo", "favicon", "icon", "/styles/")):
                continue
            if u not in seen_imgs:
                seen_imgs.add(u)
                unique_imgs.append(u)
        if unique_imgs:
            loader.add_value("images", unique_imgs[:20])

        # Documentos
        docs: list[dict] = []
        seen_doc_urls: set[str] = set()
        for a in response.css("a[href$='.pdf']"):
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

        payment_options, encumbrances = _parse_auction_clauses(body_text)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()

        # Hook para subclasses específicas refinarem o item antes do yield.
        # A default impl é no-op; subclasses sobrescrevem para preencher
        # campos que a heurística universal não cobriu, sem reimplementar
        # `parse_property` inteiro.
        self._fixup_item(item, response, body_text=body_text, host=host)

        self.log_event("ph_lote_extracted", url=response.url, host=host,
                       status=item.get("status"), min_bid=item.get("minimum_bid"),
                       mkt=item.get("market_value"))
        yield item

        edital_url = _find_edital_url(item)
        if edital_url:
            yield self.make_request(
                edital_url,
                callback=self._merge_edital_clauses,
                cb_kwargs={"item_html": item},
                errback=self._on_edital_error,
                meta={"handle_httpstatus_list": [403, 404], "dont_obey_robotstxt": True,
                      "playwright": False, "download_timeout": 15},
            )

    def _fixup_item(self, item, response, *, body_text: str, host: str) -> None:
        """Hook overridable por subclasses específicas para refinar o item
        antes do yield. Default: no-op. Subclasses devem mutar `item`
        in-place (PropertyItem é dict-like)."""
        return None

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
