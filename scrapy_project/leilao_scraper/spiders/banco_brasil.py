"""Spider para o portal oficial do Banco do Brasil — `seuimovelbb.com.br`.

Portal estático (Bootstrap 5 + jQuery), sem Playwright. Cards de imóvel
direto na home: `a[href^='/imovel/id/']`. Detalhe traz preço, descrição
legal completa com matrícula do imóvel, breadcrumb com UF.

Nota: alguns lotes têm o botão "Saiba mais" redirecionando pra plataforma
parceira (lancenoleilao, biasi, zuk). Nesta v1 capturamos os campos
expostos no portal BB sem seguir o redirect — basta para canonical_link
via matrícula CRI.

Provider slug: `banco_brasil`. Modalidade: `extrajudicial_lei_9514` para
lotes em leilão; venda direta marcada via `auction_lot.notes`.

Uso:
    scrapy crawl banco_brasil -a urls=https://www.seuimovelbb.com.br/
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


_DETAIL_HREF_RE = re.compile(r"^/imovel/id/\d+/?$")
# Padrão "RIO DE JANEIRO (RJ) - Bairro" ou "BRASILIA (DF)"
_CITY_UF_RE = re.compile(
    r"\b([A-ZÀ-Ú][A-ZÀ-Úa-zà-ú\s'.-]{2,60}?)\s*\(([A-Z]{2})\)",
)
_MATRICULA_RE = re.compile(
    r"Matr[íi]cula\s*(?:n[º°.]?\s*)?(\d{1,7})\s*do\s+(?:Registro\s+de\s+Im[óo]veis|RI|R\.I\.)[^.]{0,200}",
    re.I,
)


class BancoBrasilSpider(ProviderSpider):
    name = "banco_brasil"
    provider_slug = "banco_brasil"
    auctioneer_slug = "banco_brasil"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.0,
        "USER_AGENT": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36 TodoLeilaoBot/1.0"
        ),
    }

    MAX_LOTS_PER_RUN = 200

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._yielded = 0
        self._seen: set[str] = set()

    # ------------------------------------------------------------------
    # Nível 1: home / catalogo → lista de /imovel/id/N
    # ------------------------------------------------------------------
    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        kept = 0
        for href in response.css("a::attr(href)").getall():
            if not href:
                continue
            if not _DETAIL_HREF_RE.match(href):
                continue
            absolute = response.urljoin(href)
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
            )
        self.log_event(
            "bb_listing_done",
            host=host,
            url=response.url,
            kept=kept,
        )

        # Segue paginação /catalogo se existir
        for href in response.css(
            "a[href^='/catalogo/']::attr(href), "
            "ul.pagination a::attr(href)"
        ).getall():
            if not href:
                continue
            absolute = response.urljoin(href)
            if self.host_of(absolute) != host:
                continue
            # Só segue /catalogo/ paths que ainda não vimos via listagem
            if "/catalogo/" not in absolute:
                continue
            if absolute in self._seen:
                continue
            self._seen.add(absolute)
            yield self.make_request(
                absolute,
                callback=self.parse,
                meta={"source_listing_url": response.url},
            )

    # ------------------------------------------------------------------
    # Nível 2: detalhe /imovel/id/N
    # ------------------------------------------------------------------
    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("host", self.host_of(response.url))

        # Body text consolidado pra heurísticas
        body_text = _normalize_text(" ".join(response.css("body *::text").getall()))

        # Bloco principal de descrição: <div class="py-4">
        desc_html = " ".join(response.css("div.py-4").getall())
        desc_text = _normalize_text(re.sub(r"<[^>]+>", " ", desc_html))

        og_title = response.css("meta[property='og:title']::attr(content)").get() or ""
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""

        # Filtro de imóvel — usa descrição (BB às vezes lista mobiliário/equipamentos
        # em fundos imobiliários, mas raro)
        sample = (og_title + " " + og_desc + " " + desc_text)[:3000]
        if not _detail_is_imovel(og_title or "imóvel BB", sample):
            self.log_event("bb_lote_dropped_non_imovel", url=response.url)
            return

        loader = self.new_loader(response)
        loader.replace_value("auctioneer", "banco_brasil")

        # title — extrai ID + cidade do header da descrição
        # Formato observado: "ID76269 RIO DE JANEIRO (RJ) - Barra da Tijuca"
        m_title_header = re.search(
            r"ID\s*(\d+)\s+([A-ZÀ-Ú][^<\n]{3,100}?)(?:<br|\n|$)",
            desc_html,
        )
        bb_id = None
        title = ""
        if m_title_header:
            bb_id = m_title_header.group(1)
            title = _normalize_text(m_title_header.group(2))
        if not title:
            # Fallback: tarja-tipo-oferta + breadcrumb
            tarja = (response.css("span.tarja-tipo-oferta::text").get() or "").strip()
            breadcrumb_uf = (response.css(
                "li.breadcrumb-item a[href^='/catalogo/localidade/']::text"
            ).get() or "").strip()
            title = f"{tarja} - {breadcrumb_uf}".strip(" -") or og_title or "Imóvel BB"
        loader.add_value("title", title[:300])

        # source_lot_code — ID da BB (preferência) ou path
        if bb_id:
            loader.add_value("source_lot_code", f"bb-{bb_id}")
        else:
            m_path_id = re.search(r"/imovel/id/(\d+)", response.url)
            if m_path_id:
                loader.add_value("source_lot_code", f"bb-{m_path_id.group(1)}")

        # description (descrição legal completa)
        if desc_text:
            loader.add_value("description", desc_text[:10000])

        # status — "tarja-tipo-oferta" textual; sem badge de fechado óbvio
        tarja_lower = (response.css("span.tarja-tipo-oferta::text").get() or "").lower()
        if "encerrad" in tarja_lower or "finalizad" in tarja_lower:
            status = "desconhecido"
        elif "arrematad" in tarja_lower or "vendid" in tarja_lower:
            status = "arrematado"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Preço — div.numero traz o valor de venda; nos lotes com locação
        # também aparece "Valor de locação"; o primeiro grande BRL próximo
        # do número é o lance/venda.
        # Estratégia: pega o primeiro R$ X.XXX,XX dentro de div.numero,
        # fallback para o primeiro R$ encontrado no body.
        numero_text = _normalize_text(" ".join(response.css("div.numero *::text, div.numero::text").getall()))
        m_brl = re.search(r"R\$\s*([\d.,]+)", numero_text)
        if not m_brl:
            m_brl = re.search(r"R\$\s*([\d.,]+)", body_text)
        if m_brl:
            try:
                v = _brl_to_decimal(m_brl.group(1))
                if v and v > 0:
                    loader.add_value("minimum_bid", str(v))
            except Exception:
                pass

        # Avaliação — div.valor-avaliacao quando presente (raro no BB)
        aval_txt = _normalize_text(" ".join(response.css(
            "div.avaliacao::text, div.valor-avaliacao::text, div.valor-mercado::text"
        ).getall()))
        m_av = re.search(r"R\$\s*([\d.,]+)", aval_txt)
        if m_av:
            try:
                v = _brl_to_decimal(m_av.group(1))
                if v and v > 0:
                    loader.add_value("market_value", str(v))
            except Exception:
                pass

        # Endereço — cidade/UF extraída do título da descrição
        addr: dict[str, Any] = {"raw_text": (title or "")[:300]}
        m_cuf = _CITY_UF_RE.search(desc_text or "") or _CITY_UF_RE.search(title or "")
        if m_cuf:
            addr["municipality_name"] = m_cuf.group(1).title().strip()
            addr["uf"] = m_cuf.group(2)
        else:
            # Breadcrumb /catalogo/localidade/UF
            br_uf = response.css(
                "li.breadcrumb-item a[href^='/catalogo/localidade/']::text"
            ).get()
            if br_uf and len(br_uf.strip()) == 2:
                addr["uf"] = br_uf.strip()
        m_matr = _MATRICULA_RE.search(desc_text or "")
        if m_matr:
            addr["registry_matricula"] = m_matr.group(1)
        if any(v for v in addr.values()):
            loader.add_value("address", addr)

        # Imagens — galeria + og:image
        img_urls: list[str] = []
        for sel in (
            "div.carousel img::attr(src)",
            "div.galeria img::attr(src)",
            "img.foto::attr(src)",
            "img[src*='/imagem/imovel/']::attr(src)",
            "img[src*='/imagem/foto/']::attr(src)",
        ):
            img_urls.extend(response.css(sel).getall())
        og_img = response.css("meta[property='og:image']::attr(content)").get()
        if og_img:
            img_urls.append(og_img)
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            if not u:
                continue
            absolute = response.urljoin(u)
            low = absolute.lower()
            if any(k in low for k in ("logo", "favicon", "lg-padrao", "bandeira", "icon-")):
                continue
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs[:20])

        # Documentos PDF (edital, anexos)
        docs: list[dict] = []
        seen_docs: set[str] = set()
        for a in response.css("a[href$='.pdf'], a[href*='.pdf?']"):
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

        # Cláusulas a partir do desc_text + body
        text_for_clauses = (desc_text + " " + body_text)[:30000]
        payment_options, encumbrances = _parse_auction_clauses(text_for_clauses)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "bb_lote_extracted",
            url=response.url,
            host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            mkt=item.get("market_value"),
            matricula=(item.get("address") or {}).get("registry_matricula"),
        )
        yield item
