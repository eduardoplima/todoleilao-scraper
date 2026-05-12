"""Spider para o portal Santander Imóveis — `santanderimoveis.com.br`.

**Status: `requires_followup`.** O portal está atrás de Akamai Bot
Manager (`errors.edgesuite.net`) que retorna 403 + "Access Denied" em
TODA navegação Playwright headless — mesmo com UA realista, viewport,
locale BR e injeção anti-`webdriver`. Apenas browsers reais (non-headless
com sessão persistente) acessam. Sessão headed manual mostrou o site
funciona normalmente; precisa de uma de:
  - Browser stealth profundo (puppeteer-extra-stealth port);
  - Residential proxy + sessão persistente;
  - Sessão headed (não viável em cron / Fly.io).

Stack alvo (quando o acesso voltar a ser viável): WordPress theme
`shi/ape11`. Home renderizada vazia; listagens carregadas via XHR a
`admin-ajax.php?action=call_api` cujos parâmetros são gerados em
runtime pelo JS do tema. Para v1 usamos Playwright pra renderizar
a página de listagem e depois lemos os <a> que terminem em slug típico
de imóvel (`/imovel/{slug}-{id}` ou `/imoveis/{id}`).

Notas:
  - O Santander também opera com leiloeiros parceiros (Zuk, Biasi, Mega,
    Lance no Leilão, Frazão). Cada lote nesta vitrine tem botão "Saiba mais"
    que pode redirecionar pra plataforma do leiloeiro — só capturamos o
    que está no domínio Santander.

Provider slug: `santander`.

Uso:
    scrapy crawl santander -a urls=https://www.santanderimoveis.com.br/
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import scrapy

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _detail_is_imovel,
    _normalize_text,
    _parse_auction_clauses,
)


# Padrões observados no Santander/SHI:
#   /imovel/{slug}-{id}
#   /imoveis/{id}
#   /catalogo/{id} (raro)
_LOT_PATH_RE = re.compile(
    r"^/(?:imovel|imoveis|catalogo)/[A-Za-z0-9._-]+/?$"
)
_LOT_PATH_WITH_ID_RE = re.compile(r"[-_/](\d{2,})/?$")

_CITY_UF_RE = re.compile(
    r"\b([A-ZÀ-Ú][A-ZÀ-Úa-zà-ú\s'.-]{2,60}?)\s*[/-]\s*([A-Z]{2})\b",
)
_MATRICULA_RE = re.compile(
    r"Matr[íi]cula\s*(?:n[º°.]?\s*)?(\d{1,7})", re.I
)


class SantanderSpider(ProviderSpider):
    name = "santander"
    provider_slug = "santander"
    auctioneer_slug = "santander"
    requires_playwright = True

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 1.0,
        "PLAYWRIGHT_MAX_PAGES_PER_CONTEXT": 4,
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 60_000,
        "USER_AGENT": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36 TodoLeilaoBot/1.0"
        ),
    }

    MAX_LOTS_PER_RUN = 100

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._yielded = 0
        self._seen: set[str] = set()

    # ------------------------------------------------------------------
    # Nível 1: home/listagem renderizada
    # ------------------------------------------------------------------
    def start_requests(self) -> Iterable[Any]:
        for url in self.start_urls:
            yield self.make_request(
                url,
                callback=self.parse,
                wait_for_selector=(
                    "a[href*='/imovel/'], a[href*='/imoveis/'], "
                    ".lote, .card-imovel, .imovel-card"
                ),
                wait_timeout_ms=30_000,
                scroll_to_bottom=True,
                dont_filter=True,
            )

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        kept = 0
        for href in response.css("a::attr(href)").getall():
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            absolute = response.urljoin(href)
            if self.host_of(absolute) != host:
                continue
            path = absolute.replace(f"https://{host}", "").split("?")[0]
            if not _LOT_PATH_RE.match(path):
                continue
            if not _LOT_PATH_WITH_ID_RE.search(path):
                continue
            if absolute in self._seen:
                continue
            self._seen.add(absolute)
            if self._yielded >= self.MAX_LOTS_PER_RUN:
                break
            self._yielded += 1
            kept += 1
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url, "host": host},
                wait_for_selector="h1, h2, [class*='valor'], [class*='preco']",
                wait_timeout_ms=20_000,
            )
        self.log_event(
            "santander_listing_done",
            host=host,
            url=response.url,
            kept=kept,
        )

    # ------------------------------------------------------------------
    # Nível 2: detalhe
    # ------------------------------------------------------------------
    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("host", self.host_of(response.url))

        body_text = _normalize_text(" ".join(response.css("body *::text").getall()))
        h1 = (response.css("h1::text").get() or "").strip()
        og_title = response.css("meta[property='og:title']::attr(content)").get() or h1
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""

        sample = (og_title + " " + og_desc + " " + body_text[:3000])
        if not _detail_is_imovel(og_title or h1 or "imóvel Santander", sample):
            self.log_event("santander_lote_dropped_non_imovel", url=response.url)
            return

        loader = self.new_loader(response)
        loader.replace_value("auctioneer", "santander")

        title = og_title or h1 or "Imóvel Santander"
        if " | " in title:
            title = title.split(" | ", 1)[1].strip() or title
        loader.add_value("title", title[:300])

        m_id = re.search(r"[-_/](\d{2,})/?$", response.url)
        if m_id:
            loader.add_value("source_lot_code", f"sant-{m_id.group(1)}")

        # Description
        desc_block = " ".join(response.css(
            "div[class*='descricao'] *::text, "
            "section[class*='descricao'] *::text, "
            "div[class*='detalhes'] *::text, "
            "div.lote-descricao *::text"
        ).getall())
        desc = _normalize_text(desc_block) or og_desc
        if desc:
            loader.add_value("description", desc[:10000])

        # Status: o Santander coloca tags como "VENDIDO" ou "DISPONÍVEL"
        status_lower = (
            (response.css("[class*='status']::text").get() or "")
            + " " + (response.css("[class*='tag']::text").get() or "")
            + " " + body_text[:500]
        ).lower()
        if "encerrad" in status_lower or "finalizad" in status_lower:
            status = "desconhecido"
        elif "vendid" in status_lower or "arrematad" in status_lower:
            status = "arrematado"
        elif "suspens" in status_lower or "indispon" in status_lower:
            status = "suspenso"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Preço
        m_min = (
            re.search(
                r"(?:Pelo\s+valor\s+de|Valor\s+(?:m[íi]nimo|inicial|de\s+venda)|"
                r"Lance\s+(?:m[íi]nimo|inicial))[:\s]*R\$\s*([\d.,]+)",
                body_text, re.I,
            )
            or re.search(r"R\$\s*([\d.,]{4,})", body_text)
        )
        if m_min:
            try:
                v = _brl_to_decimal(m_min.group(1))
                if v and v > 0:
                    loader.add_value("minimum_bid", str(v))
            except Exception:
                pass

        m_av = re.search(r"Avalia[çc][ãa]o[:\s]*R\$\s*([\d.,]+)", body_text, re.I)
        if m_av:
            try:
                v = _brl_to_decimal(m_av.group(1))
                if v and v > 0:
                    loader.add_value("market_value", str(v))
            except Exception:
                pass

        # Endereço
        addr: dict[str, Any] = {"raw_text": title[:300]}
        m_cuf = _CITY_UF_RE.search((title or "") + " " + body_text[:1500])
        if m_cuf:
            cidade = m_cuf.group(1).strip().rstrip(",.")
            if 3 <= len(cidade) <= 60:
                addr["municipality_name"] = cidade.title()
                addr["uf"] = m_cuf.group(2)
        m_matr = _MATRICULA_RE.search(body_text)
        if m_matr:
            addr["registry_matricula"] = m_matr.group(1)
        if any(v for v in addr.values()):
            loader.add_value("address", addr)

        # Imagens
        img_urls = response.css("img::attr(src), img::attr(data-src)").getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            if not u or "data:image" in u:
                continue
            absolute = response.urljoin(u)
            low = absolute.lower()
            if any(skip in low for skip in (
                "logo", "favicon", "icon", "bandeira", "placeholder",
                "facebook", "instagram", "whatsapp", "wp-content/themes",
                "/src/img/")):
                continue
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs[:20])

        # Documentos
        docs: list[dict] = []
        seen_docs: set[str] = set()
        for a in response.css("a[href$='.pdf']"):
            url = a.css("::attr(href)").get()
            if not url:
                continue
            absolute = response.urljoin(url)
            if absolute in seen_docs:
                continue
            seen_docs.add(absolute)
            label = _normalize_text(" ".join(a.css("*::text").getall())) or "documento"
            docs.append({"name": label, "url": absolute})
        if docs:
            loader.add_value("documents", docs)

        payment_options, encumbrances = _parse_auction_clauses(body_text)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())
        item = loader.load_item()
        self.log_event(
            "santander_lote_extracted",
            url=response.url,
            host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            mkt=item.get("market_value"),
        )
        yield item
