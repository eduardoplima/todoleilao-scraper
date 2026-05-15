"""Spider para o provider `leiloesweb` (Leilões Web — white-label PHP/ASP).

Tenants conhecidos: `bampileiloes.com.br`, `selectleiloes.com.br`,
`leiloeslaraforster.com.br`. Mesmo template, encoding ISO-8859-1.

Recon: `specs/_providers/leiloesweb/recon.md`.

Estratégia
==========

1. Home `/` lista LEILÕES via anchors `/leilao/detalhe_leilao/{id}`.
2. Detalhe `/leilao/detalhe_leilao/{id}` traz HTML completo com:
   - `<h1>Código do Leilão: <b>X/YYYY</b></h1>`
   - Sec `lote-details` com Avaliação, Lance inicial 1º/2º Leilão, Localização
   - Bloco com descrição "Bem 1: ..." (HTML rico, com `<u>Matrícula:</u>`,
     `<u>Ônus:</u>`, etc.)
   - Imagens em `img.img-responsive` (preferir `/principal/pub/Image/` ao
     `/manage/pub/Image/` por respeito ao robots.txt)
3. XHR `lotes_regressivas.php?idLote={lot_id}` para status e bids — usado
   pelo spider de produção, mas para v1 ficamos só no HTML (status básico).

Filtro de imóvel via tipo_bem ou keywords no título/descrição.
"""
from __future__ import annotations

import html
import re
from typing import Iterable
from urllib.parse import urlparse

import scrapy

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import _brl_to_decimal, _normalize_text


_LEILAO_HREF_RE = re.compile(r"/leilao/detalhe_leilao/(\d+)")
_LOTE_ID_RE = re.compile(r"idLote=(\d+)")

# "22 de Abril de 2026 às 14h00"
_PT_DT_RE = re.compile(
    r"(\d{1,2})\s+de\s+([A-Za-zçÇ]+)\s+de\s+(\d{4})\s+[àa]s\s+(\d{1,2})h(\d{2})",
    re.I,
)
_MONTH_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _parse_pt_date(text: str) -> str | None:
    if not text:
        return None
    m = _PT_DT_RE.search(text)
    if not m:
        return None
    d, mname, y, h, mi = m.groups()
    mnum = _MONTH_PT.get(mname.lower().strip())
    if not mnum:
        return None
    return f"{y}-{mnum:02d}-{int(d):02d}T{int(h):02d}:{mi}:00-03:00"


_RE_IMOVEL = re.compile(
    r"\b(im[óo]ve(?:l|is)|imove(?:l|is)|casa|apartamento|apto|sobrado|kitnet|"
    r"loja|sala|comercial|terreno|ch[áa]cara|fazenda|s[íi]tio|[áa]rea|rural|"
    r"galp[ãa]o|gleba|edif[íi]cio|pr[ée]dio|cobertura|flat|loft|vaga)\b",
    re.I,
)
_RE_NOT_IMOVEL = re.compile(
    r"\b(ve[íi]culo|automóvel|automotivo|motocicleta|caminh[ãa]o)\b",
    re.I,
)

_TYPE_MAP = {
    "apartamento": "apartamento",
    "apto": "apartamento",
    "casa": "casa",
    "sobrado": "casa",
    "kitnet": "apartamento",
    "cobertura": "apartamento",
    "flat": "apartamento",
    "terreno": "terreno",
    "gleba": "terreno",
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
    "comercial": "comercial",
    "vaga": "outro",
    "edifício": "apartamento",
    "edificio": "apartamento",
}


def _classify(title: str) -> str | None:
    t = (title or "").lower()
    for key, val in _TYPE_MAP.items():
        if key in t:
            return val
    return None


def _is_imovel(text: str) -> bool:
    t = text or ""
    if _RE_NOT_IMOVEL.search(t) and not _RE_IMOVEL.search(t):
        return False
    return bool(_RE_IMOVEL.search(t))


class LeiloeswebSpider(ProviderSpider):
    name = "leiloesweb"
    provider_slug = "leiloesweb"
    auctioneer_slug = "leiloesweb"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
        # Pages são ISO-8859-1; scrapy lê o `<meta charset>` e decode certo.
    }

    MAX_LEILOES_PER_HOST = 200

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_leiloes: set[str] = set()

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        # Home traz anchors `/leilao/detalhe_leilao/{id}#conteudo`.
        ids: list[str] = []
        for href in response.css("a::attr(href)").getall():
            m = _LEILAO_HREF_RE.search(href)
            if m and m.group(1) not in self._seen_leiloes:
                ids.append(m.group(1))
                self._seen_leiloes.add(m.group(1))
                if len(ids) >= self.MAX_LEILOES_PER_HOST:
                    break

        self.log_event("lw_home_leiloes", host=host, count=len(ids))
        for leilao_id in ids:
            url = response.urljoin(f"/leilao/detalhe_leilao/{leilao_id}")
            yield self.make_request(
                url,
                callback=self.parse_leilao,
                meta={
                    "source_listing_url": response.url,
                    "broker_host": host,
                    "leilao_id": leilao_id,
                },
            )

    def parse_leilao(self, response: scrapy.http.Response):
        """Cada leilão é uma única página com 1+ lotes — emitimos 1 PropertyItem por leilão.

        Para leilões multi-lote, a separação está no HTML como "Bem 1", "Bem 2"
        dentro de um <p> só. v1 emite um item agregado (description contém
        todos os bens); v2 pode separar em itens distintos via `Bem N:` regex.
        """
        host = response.meta.get("broker_host") or self.host_of(response.url)
        leilao_id = response.meta.get("leilao_id")
        body_text = " ".join(response.css("body *::text").getall())[:15000]
        # response.text mantém entidades HTML (`&ccedil;` etc) — decodificamos
        # para a regex pegar acentos diretamente.
        page_html = html.unescape(response.text)

        # Filtro de imóvel — checar pelo body
        if not _is_imovel(body_text[:5000]):
            self.log_event("lw_dropped_non_imovel", url=response.url,
                           leilao_id=leilao_id)
            return

        loader = self.new_loader(response)
        loader.replace_value("auctioneer", f"leiloesweb::{host}")

        # source_lot_code: idLote do XHR no script inline
        m_lot = _LOTE_ID_RE.search(response.text)
        if m_lot:
            loader.add_value("source_lot_code", m_lot.group(1))
        elif leilao_id:
            loader.add_value("source_lot_code", f"leilao-{leilao_id}")

        # Title: <h1>Código do Leilão: <b>X/YYYY</b></h1> + <title>
        page_title = (response.css("title::text").get() or "").strip()
        codigo = response.css("h1 b::text").get()
        if page_title:
            title = page_title
            if codigo:
                title = f"{codigo} — {page_title}"
            loader.add_value("title", _normalize_text(title))

        # property_type
        pt = _classify(body_text[:3000])
        if pt:
            loader.add_value("property_type", pt)

        # Status default
        bt_low = body_text.lower()
        if "arrematad" in bt_low:
            status = "arrematado"
        elif "encerrad" in bt_low or "fechad" in bt_low:
            status = "desconhecido"
        elif "suspens" in bt_low:
            status = "suspenso"
        elif "cancelad" in bt_low:
            status = "cancelado"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # ---- Avaliação / lance inicial 1º e 2º ----
        av_m = re.search(
            r"Avalia[çc][ãa]o\s*:?\s*</[^>]+>\s*</[^>]+>\s*<[^>]+>\s*<[^>]+>\s*<p>R\$\s*([\d.,]+)",
            page_html, re.I | re.S,
        )
        if not av_m:
            av_m = re.search(r"Avalia[çc][ãa]o\s*:.{0,200}?R\$\s*([\d.,]+)",
                              page_html, re.I | re.S)
        if av_m:
            try:
                loader.add_value("market_value", str(_brl_to_decimal(av_m.group(1))))
            except Exception:
                pass

        # Lance inicial 1º Leilão
        first_min = None
        m1 = re.search(
            r"Lance\s+inicial\s+em\s+1[º°.]?\s+Leil[ãa]o\s*:.{0,200}?R\$\s*([\d.,]+)",
            page_html, re.I | re.S,
        )
        if m1:
            try:
                first_min = str(_brl_to_decimal(m1.group(1)))
            except Exception:
                pass

        # Lance inicial 2º Leilão
        second_min = None
        m2 = re.search(
            r"Lance\s+inicial\s+em\s+2[º°.]?\s+Leil[ãa]o\s*:.{0,200}?R\$\s*([\d.,]+)",
            page_html, re.I | re.S,
        )
        if m2:
            try:
                second_min = str(_brl_to_decimal(m2.group(1)))
            except Exception:
                pass

        # minimum_bid = menor entre os dois (2ª praça normalmente)
        candidates = []
        if first_min:
            candidates.append(first_min)
        if second_min:
            candidates.append(second_min)
        if candidates:
            from decimal import Decimal as _D
            loader.add_value("minimum_bid", str(min(_D(c) for c in candidates)))

        # Datas das praças
        m_d1 = re.search(
            r"1[º°.]?\s+Leil[ãa]o\s*:.{0,200}?(\d{1,2}\s+de\s+\w+\s+de\s+\d{4}\s+[àa]s\s+\d{1,2}h\d{2})",
            page_html, re.I | re.S,
        )
        m_d2 = re.search(
            r"2[º°.]?\s+Leil[ãa]o\s*:.{0,200}?(\d{1,2}\s+de\s+\w+\s+de\s+\d{4}\s+[àa]s\s+\d{1,2}h\d{2})",
            page_html, re.I | re.S,
        )
        if m_d1:
            iso = _parse_pt_date(m_d1.group(1))
            if iso:
                loader.add_value("first_auction_date", iso)
        if m_d2:
            iso = _parse_pt_date(m_d2.group(1))
            if iso:
                loader.add_value("second_auction_date", iso)
        if m_d1 and m_d2:
            loader.add_value("auction_phase", "2a_praca")
        elif m_d1:
            loader.add_value("auction_phase", "1a_praca")

        # Localização
        loc_m = re.search(
            r"Localiza[çc][ãa]o\s*:.{0,200}?<p>([^<]+)</p>",
            page_html, re.I | re.S,
        )
        if loc_m:
            loc = _normalize_text(loc_m.group(1))
            addr: dict = {"raw_text": loc}
            m_uf = re.search(r"/\s*([A-Z]{2})\s*$", loc)
            if m_uf:
                addr["uf"] = m_uf.group(1)
                m_city = re.match(r"^(.+?)\s*/\s*[A-Z]{2}\s*$", loc)
                if m_city:
                    addr["municipality_name"] = m_city.group(1).strip().title()
            loader.add_value("address", addr)

        # Descrição: bloco textual após `<u>Bem 1:</u>` ou similar. v1 pega
        # o primeiro `<p class="Textbody">...</p>` ou agregado.
        desc_nodes = response.css(
            "p.Textbody *::text, "
            "div.detalhamento *::text, "
            "div.descricao-lote *::text"
        ).getall()
        desc = _normalize_text(" ".join(desc_nodes))
        if len(desc) < 50:
            # Fallback: pegar entire descricao after "Descrição do bem" header
            desc_section = re.search(
                r"(Descri[çc][ãa]o\s+do\s+bem.{0,30000})",
                page_html, re.I | re.S,
            )
            if desc_section:
                cleaned = re.sub(r"<[^>]+>", " ", desc_section.group(1)[:15000])
                desc = _normalize_text(cleaned)
        if desc:
            loader.add_value("description", desc[:10000])

        # Imagens — prefer /principal/pub/Image/ (robots-friendly)
        imgs: list[str] = []
        seen_imgs: set[str] = set()
        for src in response.css("img.img-responsive::attr(src), img.img_lote::attr(src)").getall():
            if not src:
                continue
            normalized = src.replace("/manage/pub/Image/", "/principal/pub/Image/")
            absolute = response.urljoin(normalized)
            if absolute not in seen_imgs:
                seen_imgs.add(absolute)
                imgs.append(absolute)
        if imgs:
            loader.add_value("images", imgs)

        # Documentos — links PDF
        docs: list[dict] = []
        seen_doc_urls: set[str] = set()
        for a in response.css("a[href$='.pdf'], a[href*='/pub/anexos/']"):
            href = a.css("::attr(href)").get() or ""
            if not href:
                continue
            label = _normalize_text(" ".join(a.css("*::text").getall()))
            absolute = response.urljoin(href).replace(
                "/manage/pub/", "/principal/pub/",
            )
            if absolute in seen_doc_urls:
                continue
            seen_doc_urls.add(absolute)
            docs.append({"name": label or "documento", "url": absolute})
        if docs:
            loader.add_value("documents", docs)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "lw_lote_extracted",
            url=response.url,
            host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            market=item.get("market_value"),
        )
        yield item
