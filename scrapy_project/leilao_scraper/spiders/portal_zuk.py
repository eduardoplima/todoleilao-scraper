"""Spider para o provider Portal Zuk (Zukerman / Dora Plat).

Plataforma single-tenant. Vários leiloeiros do INNLEI (Fabio Zukerman,
Cezar A. Badolato Silva, Dora Plat, BVA, LUT etc.) operam pelo mesmo
back-end Laravel + jQuery em www.portalzuk.com.br. ~7 hosts redirecionam
para esse domínio; spider trata como um único site canônico.

Recon: specs/_providers/portal_zuk/.

Estratégia:
  - Listing `/leilao-de-imoveis` é server-side render Laravel: 30 cards
    SSR no DOM já na primeira carga (sem precisar de JS).
  - Paginação real ("Carregar mais") via POST com CSRF (rota nominada
    `carrega.mais`); não implementada em v1 — alternativa Playwright
    com scroll-to-bottom + click-load-more cobre até ~150 lotes por
    sessão (cap conservador), o que é suficiente para a quantidade
    típica de imóveis abertos (~30-50 por mês).
  - Detail `/imovel/{uf}/{cidade}/{bairro}/{rua}/{id1}-{id2}` é
    SSR completo: header, área, endereço, datas das 2 praças, galeria,
    documentos.

Particularidades:
  - Cloudflare ativo mas libera com UA Chrome real.
  - robots.txt bloqueia /edital — links de edital ficam no detail page,
    mas spider não faz crawl recursivo desses arquivos.
  - Bid history requer login (container #maior-lance-login mostra "Entrar
    para ver lances"). bids[] sempre vazio para anônimo.

Uso:
    scrapy crawl portal_zuk -a sites=1
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

import scrapy

from leilao_scraper.spiders._common_ua import BROWSER_USER_AGENT
from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _BRL_RE,
    _brl_to_decimal,
    _dedup_clauses,
    _detail_is_imovel,
    _normalize_text,
    _parse_auction_clauses,
)


# Regex pra extrair (id_partner, id_imovel) do path "/imovel/<UF>/.../<id1>-<id2>"
_IMOVEL_PATH_RE = re.compile(r"/imovel/[a-z]{2}/[^/]+/[^/]+/[^/]+/(\d+)-(\d+)/?")


# UF do path; sempre 2 letras
_PATH_UF_RE = re.compile(r"/imovel/([a-z]{2})/", re.I)


# Texto "DD/MM/YY às HHhMM"; tolerante a "DD/MM/YYYY" com 4 dígitos
_DATE_TIME_RE = re.compile(
    r"(\d{2})/(\d{2})/(\d{2,4})\s*(?:[àa]s\s*)?(\d{1,2})h(\d{2})?",
    re.I,
)


class PortalZukSpider(ProviderSpider):
    name = "portal_zuk"
    provider_slug = "portal_zuk"
    auctioneer_slug = "portal_zuk"
    requires_playwright = False  # listing+detail SSR sem JS necessário em v1

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
        "USER_AGENT": BROWSER_USER_AGENT,
    }

    LISTING_PATHS = (
        # Default: lista de imóveis abertos (30 cards SSR + carregar-mais)
        "/leilao-de-imoveis",
        # Filtros por categoria que retornam HTML SSR distinto e amplia
        # a cobertura sem JS:
        "/leilao-de-imoveis/t/todos-imoveis/residenciais",
        "/leilao-de-imoveis/t/todos-imoveis/comerciais",
        "/leilao-de-imoveis/t/todos-imoveis/rurais",
        "/leilao-de-imoveis/t/todos-imoveis/terrenos",
    )

    def start_requests(self) -> Iterable[Any]:
        self._open_incremental_db()
        # ProviderSpider.start_urls vem do site_providers.csv (vários hosts
        # apontam pra portalzuk.com.br); deduplicamos por host canônico.
        canonical_host = "www.portalzuk.com.br"
        self._listing_seen: set[str] = set()
        for path in self.LISTING_PATHS:
            url = f"https://{canonical_host}{path}"
            yield self.make_request(
                url,
                callback=self.parse_listing,
                meta={"host": "portalzuk.com.br", "source_listing_url": url},
            )

    def closed(self, reason: str) -> None:
        self.close_incremental_db()

    # ------------------------------------------------------------------
    # Nível 1: home / categoria → cards SSR
    # ------------------------------------------------------------------
    def parse_listing(
        self, response: scrapy.http.Response
    ) -> Iterable[scrapy.Request]:
        host = response.meta["host"]
        # Cards que apontam para detail estão em <div class="card_lotes_div">.
        # Existem 2 tipos de card no mesmo HTML: o card principal "card-property"
        # (no fluxo de busca) e cards menores em carrossel (lotes em destaque).
        # Ambos têm href de detail; deduplicamos por href.
        seen_local: set[str] = set()
        kept = 0
        dropped = 0
        for href in response.css(
            "div.card_lotes_div a[href*='/imovel/']::attr(href)"
        ).getall():
            absolute = response.urljoin(href).split("?")[0]
            if absolute in self._listing_seen or absolute in seen_local:
                continue
            seen_local.add(absolute)
            self._listing_seen.add(absolute)

            m = _IMOVEL_PATH_RE.search(absolute)
            if not m:
                dropped += 1
                continue
            lot_code = f"{m.group(1)}-{m.group(2)}"

            if self.lot_exists(host, lot_code):
                yield self.make_listing_only_item(
                    url=absolute,
                    source_lot_code=lot_code,
                    auctioneer=f"portal_zuk::{host}",
                )
                kept += 1
                continue

            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url, "host": host},
            )
            kept += 1

        self.log_event(
            "zuk_listing_done",
            url=response.url,
            kept=kept,
            dropped=dropped,
            seen_global=len(self._listing_seen),
        )

    # ------------------------------------------------------------------
    # Nível 2: detail → PropertyItem
    # ------------------------------------------------------------------
    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("host", self.host_of(response.url))

        # Filtro defensivo de imóvel (a URL já tem /imovel/, mas confirma
        # via og:title/description pra pegar lots reclassificados).
        og_title = (
            response.css("meta[property='og:title']::attr(content)").get() or ""
        )
        og_desc = (
            response.css("meta[property='og:description']::attr(content)").get() or ""
        )
        if not _detail_is_imovel(og_title, og_desc):
            self.log_event(
                "zuk_lot_dropped_non_imovel",
                url=response.url,
                og_title=og_title[:80],
            )
            return

        loader = self.new_loader(response)
        loader.replace_value("auctioneer", f"portal_zuk::{host}")

        # source_lot_code
        m = _IMOVEL_PATH_RE.search(response.url)
        lot_code = None
        if m:
            lot_code = f"{m.group(1)}-{m.group(2)}"
            loader.add_value("source_lot_code", lot_code)

        # title — h1.title do property-main-content (NÃO o h1.title da página
        # toda; a related-lots carousel não tem h1 mas o filtro garante).
        title = (
            response.css("div.property-main-content h1.title::text").get()
            or response.css("div.property-area h1.title::text").get()
            or og_title
        ).strip()
        if title:
            loader.add_value("title", title)

        # description — meta og:description; o body só tem texto distribuído
        if og_desc:
            loader.add_value("description", og_desc.strip()[:10000])

        # property_type — keyword do title ("Casa", "Apartamento", "Terreno"
        # etc.). Loader.detect_property_type lida com isso quando preenchido
        # via title.

        # endereço — propertyaddress dentro do property-main-content
        addr_raw = " ".join(
            response.css(
                "div.property-main-content p.property-address *::text, "
                "div.property-main-content p.property-address::text"
            ).getall()
        )
        addr_raw = _normalize_text(addr_raw)
        if addr_raw:
            loader.add_value("address", _parse_address(addr_raw, response.url))

        # Praças — extraídas dos card-action-item dentro do main content.
        # Estrutura típica:
        #   div.card-action-item
        #     span.card-action-item-text   "1º Leilão"
        #     span.card-action-item-date   "18/05/26 às 10h40"
        #     span.card-action-item-value  "R$ 376.888,87"
        first_dt = None
        first_value = None
        second_dt = None
        second_value = None
        for item in response.css("div.property-main-content .card-action-item"):
            label = _normalize_text(
                " ".join(item.css("span.card-action-item-text *::text, "
                                  "span.card-action-item-text::text").getall())
            ).lower()
            date_text = _normalize_text(
                " ".join(item.css("span.card-action-item-date *::text, "
                                  "span.card-action-item-date::text").getall())
            )
            value_text = _normalize_text(
                " ".join(item.css("span.card-action-item-value *::text, "
                                  "span.card-action-item-value::text").getall())
            )
            value_m = _BRL_RE.search(value_text)
            value = None
            if value_m:
                try:
                    value = _brl_to_decimal(value_m.group(1))
                except (InvalidOperation, ValueError):
                    value = None
            dt = _parse_zuk_datetime(date_text)
            if "1" in label and "leil" in label:
                first_dt = dt or first_dt
                first_value = value or first_value
            elif "2" in label and "leil" in label:
                second_dt = dt or second_dt
                second_value = value or second_value

        # market_value = avaliação do 1ª praça (geralmente o valor cheio).
        # minimum_bid = valor da praça que estiver vigente — preferência:
        # 2ª praça se existe; senão 1ª.
        if first_value is not None:
            loader.add_value("market_value", str(first_value))
        # min_bid = 2ª praça se houver (preço com desconto); senão 1ª = mkt
        if second_value is not None:
            loader.add_value("minimum_bid", str(second_value))
        elif first_value is not None:
            loader.add_value("minimum_bid", str(first_value))

        if first_dt:
            loader.add_value("first_auction_date", first_dt)
        if second_dt:
            loader.add_value("second_auction_date", second_dt)
            loader.add_value("auction_phase", "2a_praca")
        elif first_dt:
            loader.add_value("auction_phase", "1a_praca")

        # imagens — galeria; o portal usa figure.property-gallery-image
        # como container e img absoluto em https://imagens.portalzuk.com.br/...
        img_urls: list[str] = []
        for src in response.css(
            "figure.property-gallery-image img::attr(src)"
        ).getall():
            if src:
                img_urls.append(response.urljoin(src))
        # Dedup
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            if u in seen_imgs:
                continue
            seen_imgs.add(u)
            unique_imgs.append(u)
        if unique_imgs:
            loader.add_value("images", unique_imgs)

        # documentos — PDFs (edital, laudo). robots.txt bloqueia /edital
        # mas o link no detail page é referência pública; spider apenas
        # registra a URL — NÃO baixa.
        docs: list[dict] = []
        for a in response.css(
            "div.property-main-content a[href$='.pdf']"
        ):
            url = a.css("::attr(href)").get()
            if not url:
                continue
            label = _normalize_text(" ".join(a.css("*::text").getall())) or "documento"
            abs_url = response.urljoin(url)
            docs.append({"name": label, "url": abs_url})
        if docs:
            loader.add_value("documents", docs)

        # Cláusulas (CPC 130, payment installments etc.)
        page_text = _normalize_text(
            " ".join(response.css("div.property-main-content *::text").getall())
        )
        payment_options, encumbrances = _parse_auction_clauses(page_text)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        # status — sem badge claro no portalzuk; por default "aberto" se as
        # praças têm datas futuras. Se o texto do main-content disser
        # "encerrado/arrematado/cancelado", refletir.
        body_blob = page_text.lower()
        if "arrematado" in body_blob:
            status = "arrematado"
        elif "leilão encerrado" in body_blob or "encerrado em" in body_blob:
            status = "desconhecido"  # encerrado sem mais info
        elif "suspens" in body_blob:
            status = "suspenso"
        elif "cancel" in body_blob:
            status = "cancelado"
        else:
            status = "aberto"
        loader.add_value("status", status)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "zuk_lot_extracted",
            url=response.url,
            lot_code=lot_code,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            mkt=item.get("market_value"),
            imgs=len(item.get("images") or []),
        )
        yield item


# ---------------------------------------------------------------------------
# Helpers locais
# ---------------------------------------------------------------------------


def _parse_zuk_datetime(text: str) -> str | None:
    """Extrai 'DD/MM/YYYY HH:MM' do formato 'DD/MM/YY às HHhMM'."""
    if not text:
        return None
    m = _DATE_TIME_RE.search(text)
    if not m:
        return None
    d, mo, y, h, mi = m.groups()
    # Normaliza ano: '26' → '2026'; assume século 21 quando 2 dígitos.
    if len(y) == 2:
        y = f"20{y}"
    mi = mi or "00"
    return f"{d}/{mo}/{y} {int(h):02d}:{mi}"


def _parse_address(raw: str, url: str) -> dict:
    """'Rua Projetada 03, 55 - Novo Irecê - Irecê / BA' → dict estruturado."""
    cleaned = _normalize_text(raw)
    out: dict[str, Any] = {"raw_text": cleaned[:300]}

    # UF tentado do path (mais confiável)
    m_uf_path = _PATH_UF_RE.search(url)
    if m_uf_path:
        out["uf"] = m_uf_path.group(1).upper()

    # Estrutura textual: 'Rua X, 55 - Bairro - Cidade / UF'
    # Use o último '/' como separador da UF se presente
    m_uf_text = re.search(r"/\s*([A-Z]{2})\s*$", cleaned)
    if m_uf_text and "uf" not in out:
        out["uf"] = m_uf_text.group(1)

    # Cidade entre '-' e '/UF' ou último '-' do segmento
    m_city = re.search(r"-\s*([^-/]+?)\s*/\s*[A-Z]{2}\s*$", cleaned)
    if m_city:
        out["municipality_name"] = m_city.group(1).strip()

    # Bairro: penúltimo segmento entre '-'
    parts = [p.strip() for p in cleaned.split(" - ")]
    if len(parts) >= 3:
        out["neighborhood"] = parts[-2]

    # Rua + número: primeiro segmento
    if parts:
        first = parts[0]
        m_rn = re.match(r"^(.+?),\s*([\dSNs/-]+)\s*$", first)
        if m_rn:
            out["street"] = m_rn.group(1).strip()
            out["number"] = m_rn.group(2).strip()
        else:
            out["street"] = first.strip()
    return out
