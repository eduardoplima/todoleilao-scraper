"""Portal Zuk (www.portalzuk.com.br) — **maior portal residencial do
Brasil** (Itaú, Santander, Bradesco, Caixa, Poupex, e parceiros).

Antes classificado como `desconhecido` no `site_providers.csv` porque
não correspondia a nenhuma plataforma SaaS conhecida. Hoje promovido
a slug próprio (`portalzuk`).

**Decisão técnica importante**: portalzuk é estático (server-side
rendered, Laravel/Blade), NÃO precisa Playwright. Sobrescrevemos
`requires_playwright = False` e desabilitamos as page methods do
PhSpider. Isso permite paralelismo muito maior.

URL pattern:
  - Listing: `/leilao-de-imoveis` (e variantes /t/, /c/, /r/, /u/, /v/)
  - Detail: `/imovel/{uf}/{cidade}/{bairro}/{addr-slug}/{leilaoId}-{productId}`

Markup-chave do detail page (inline JS block após `<script>`):
  ```js
  'leilaoId':'36167',
  'productId':'224618',
  'price':'111750',
  'tipoImovel':'Casa',
  'uf':'BA',
  'cidade':'Juazeiro',
  'bairro':'Alto do Cruzeiro',
  'comitente':'Banco Santander Brasil S/A',
  ```

Estratégia:
  1. Extrair o bloco `'comitente':'...'` e ADICIONÁ-LO ao campo
     `description` no formato `"\\n\\nComitente: {nome}"` — assim o
     trigger SQL `core.extract_creditors()` (que faz regex sobre
     description) pega automaticamente.
  2. Extrair `price` da inline JS (mais confiável que regex sobre body
     porque o body tem múltiplos R$).
  3. Usar `tipoImovel`/`uf`/`cidade`/`bairro` para preencher address
     estruturado.
"""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlparse

import scrapy

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider
from leilao_scraper.spiders.proprio_html_specific._common import (
    collect_pdfs_with_query,
)
from leilao_scraper.spiders.soleon import _brl_to_decimal, _normalize_text


# Regex sobre o inline JS data block do Portalzuk
_RE_ZUK_FIELD = re.compile(
    r"'(?P<key>leilaoId|productId|codZ|price|tipoImovel|uf|cidade|"
    r"bairro|comitente)'\s*:\s*'(?P<value>[^']*)'",
    re.I,
)

# Detail URL pattern
_DETAIL_URL_RE = re.compile(r"/imovel/[^/]+/[^/]+/[^/]+/[^/]+/\d+-\d+")

# Listing browse paths
_LISTING_PATHS = [
    "/leilao-de-imoveis",
    "/leilao-de-imoveis/t/todos-imoveis/residenciais",
    "/leilao-de-imoveis/t/todos-imoveis/comerciais",
    "/leilao-de-imoveis/t/todos-imoveis/terrenos",
    "/leilao-de-imoveis/t/todos-imoveis/rurais",
]


class PortalzukSpider(ProprioHtmlSpider):
    name = "portalzuk"
    provider_slug = "portalzuk"
    auctioneer_slug = "portalzuk"

    # Portalzuk é SSR — Playwright opcional, mas mantemos True para
    # consistência com o pipeline padrão de `proprio_html`. Em produção
    # com volume alto, considerar override para False.
    requires_playwright = True

    custom_settings = {
        **ProprioHtmlSpider.custom_settings,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 0.8,
    }

    MAX_LOTS_PER_SITE = 60

    # ----------------------------------------------------------------
    # Override parse: começa pelas listings, não pela home (que tem só
    # 30 cards repetidos e mistura categorias)
    # ----------------------------------------------------------------

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        state = self._host_state.setdefault(host, {
            "lot_urls_seen": set(),
            "listing_fallbacks_tried": 0,
            "category_urls_seen": set(),
            "lots_yielded": 0,
        })

        # Coleta lotes da home E dispara listings categorizadas.
        lot_links = self._extract_lot_links(response, host)
        if lot_links:
            self.log_event("zuk_home_yielded", host=host, kept=len(lot_links))
            yield from self._yield_lots(lot_links, response.url, host, state)

        # Sempre tenta as listings tipadas — diversifica categorias.
        for path in _LISTING_PATHS:
            url = response.urljoin(path)
            if url in state.get("category_urls_seen", set()):
                continue
            state.setdefault("category_urls_seen", set()).add(url)
            yield self.make_request(
                url,
                callback=self.parse_listing_fallback,
                meta={"host": host, "fallback_path": path},
            )

    def _extract_lot_links(self, response, host):
        """Override: usa pattern específico do portalzuk (mais preciso)."""
        seen: set[str] = set()
        result: list[str] = []
        for href in response.css("a::attr(href)").getall():
            if not href:
                continue
            absolute = response.urljoin(href)
            if self.host_of(absolute) != host:
                continue
            if absolute in seen:
                continue
            if not _DETAIL_URL_RE.search(absolute):
                continue
            seen.add(absolute)
            result.append(absolute)
        return result

    # ----------------------------------------------------------------
    # parse_property: reimplementado para usar o inline JS block
    # ----------------------------------------------------------------

    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("host", self.host_of(response.url))

        # Extrai bloco JS estruturado
        zuk_data: dict[str, str] = {}
        for m in _RE_ZUK_FIELD.finditer(response.text):
            zuk_data[m.group("key")] = m.group("value").strip()

        og_title = response.css("meta[property='og:title']::attr(content)").get() or ""
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""
        h1 = (response.css("h1::text").get() or "").strip()
        body_text = _normalize_text(" ".join(response.css("body *::text").getall()))

        # `og:title` tem cidade/UF/cod no formato canônico
        # Ex: "Leilão de Casa - Alto do Cruzeiro - Juazeiro/BA cod: 224618"
        title = og_title or h1
        if " | " in title:
            title = title.split(" | ", 1)[0].strip()

        loader = self.new_loader(response)
        loader.replace_value("auctioneer", "portalzuk")
        if title:
            loader.add_value("title", title)

        # source_lot_code = productId
        if zuk_data.get("productId"):
            loader.add_value("source_lot_code", zuk_data["productId"])

        # Description: og:desc + comitente (importante para o trigger SQL)
        desc_parts: list[str] = []
        if og_desc:
            desc_parts.append(og_desc.strip())

        # Descrição rica do imóvel se houver
        desc_body = " ".join(response.css(
            "div.descricao-imovel *::text, "
            "div[class*='descricao'] *::text, "
            "section[class*='descricao'] *::text"
        ).getall())
        desc_body = _normalize_text(desc_body)
        if desc_body and len(desc_body) > 50:
            desc_parts.append(desc_body[:5000])

        # COMITENTE — chave do trabalho (alimenta extract_creditors via trigger SQL)
        comitente = zuk_data.get("comitente", "").strip()
        if comitente:
            desc_parts.append(f"\nComitente: {comitente}")
            self.log_event("zuk_comitente_detected",
                           comitente=comitente, url=response.url)

        if desc_parts:
            loader.add_value("description", "\n\n".join(desc_parts))

        # minimum_bid: do `price` inline (em reais inteiros)
        price_raw = zuk_data.get("price")
        if price_raw:
            try:
                v = _brl_to_decimal(price_raw)
                if v and v > 0:
                    loader.add_value("minimum_bid", str(v))
            except Exception:
                pass
        else:
            # fallback: "Em leilão pelo valor de R$ X"
            m_val = re.search(r"Em\s+leil[ãa]o\s+pelo\s+valor\s+de\s*R\$\s*([\d.,]+)",
                              body_text, re.I)
            if m_val:
                try:
                    v = _brl_to_decimal(m_val.group(1))
                    if v and v > 0:
                        loader.add_value("minimum_bid", str(v))
                except Exception:
                    pass

        # Address estruturado
        addr: dict = {}
        if zuk_data.get("uf"):
            addr["uf"] = zuk_data["uf"]
        if zuk_data.get("cidade"):
            addr["municipality_name"] = zuk_data["cidade"]
        if zuk_data.get("bairro"):
            addr["neighborhood"] = zuk_data["bairro"]
        # Tenta extrair logradouro do URL path
        parsed = urlparse(response.url)
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) >= 6 and path_parts[0] == "imovel":
            # path: imovel / uf / cidade / bairro / addr-slug / id-id
            addr["raw_text"] = path_parts[4].replace("-", " ").replace("_", " ")
        if addr:
            loader.add_value("address", addr)

        # property_type a partir de tipoImovel
        tipo = zuk_data.get("tipoImovel", "").strip().lower()
        if tipo:
            if tipo in ("casa", "sobrado"):
                loader.add_value("property_type", "casa")
            elif "apart" in tipo:
                loader.add_value("property_type", "apartamento")
            elif "terren" in tipo or "lote" in tipo:
                loader.add_value("property_type", "terreno")
            elif "comerc" in tipo or "loja" in tipo or "sala" in tipo:
                loader.add_value("property_type", "comercial")
            elif "rural" in tipo or "fazend" in tipo or "ch[áa]cara" in tipo:
                loader.add_value("property_type", "rural")
            else:
                loader.add_value("property_type", "outro")

        # Imagens (filtra logos/feedback)
        img_urls = response.css("img::attr(src), img::attr(data-src)").getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            if not u or "data:image" in u:
                continue
            absolute = response.urljoin(u)
            low = absolute.lower()
            if any(skip in low for skip in (
                "logo", "favicon", "icon", "feedback", "comitentes/",
                "/blog/", "/mini/", "/cdn.portalzuk.com.br/assets/",
                "facebook", "instagram", "whatsapp",
            )):
                continue
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs[:20])

        # Documents (edital + matrícula)
        docs = collect_pdfs_with_query(response)
        if docs:
            loader.add_value("documents", docs)

        # Datas — "Encerra em DD/MM/YY às HHhMM"
        m_date = re.search(
            r"Encerra\s+em\s+(\d{2}/\d{2}/\d{2,4})\s+[àa]s\s+(\d{2}h\d{2})",
            body_text, re.I,
        )
        if m_date:
            dt_str = f"{m_date.group(1)} {m_date.group(2).replace('h', ':')}"
            loader.add_value("second_auction_date", dt_str)

        # Status
        if "encerrado" in body_text.lower()[:1000]:
            loader.add_value("status", "desconhecido")
        else:
            loader.add_value("status", "aberto")

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event("zuk_lote_extracted", url=response.url, host=host,
                       comitente=comitente or "?",
                       min_bid=item.get("minimum_bid"),
                       product_id=zuk_data.get("productId", "?"))
        yield item
