"""Spider para `oaleiloes.com.br` (Bruno Duarte + Orlando Araújo, OALeilões).

Topologia do site:

  /                    home — lista links para auctions ativos (/leilao/{id})
  /leilao/{id}         página do leilão — agrupa N lotes (/lote/{id}/{slug})
  /lote/{id}/{slug}    página do lote — um imóvel ou bem

Algumas leilões mesclam imóveis com veículos/eletrônicos. Filtramos no nível
do anchor do `parse_leilao` lendo o texto da categoria (ex.: "IMÓVEIS URBANOS
/ CASAS"). Lots sem categoria de imóvel são ignorados em vez de chegar até
o `detect_property_type` do loader retornar None.
"""
from __future__ import annotations

import re

from leilao_scraper.loaders import normalize_uf

from .base import BaseAuctionSpider

PROPERTY_CATEGORY_RE = re.compile(
    r"\b(imov|imóv|apartament|apto|casa|terreno|lote\s+urb|sala\s+coml|galp|chacar|sitio|fazenda|loft|cobertura|kitnet)",
    re.IGNORECASE,
)

# 'AL/MACEIO. RUA WALFRIDO ROCHA, N. 206, Apto. 902, ...'
ADDRESS_RE = re.compile(
    r"\b([A-Z]{2})\s*/\s*([A-ZÀ-Ý][A-ZÀ-Ý\s]+?)\.\s*(.+?)(?:\s+MATR[IÍ]CULA|\s+OF[IÍ]CIO|\s*$)",
    re.IGNORECASE,
)


class OALeiloesSpider(BaseAuctionSpider):
    name = "oaleiloes"
    auctioneer_slug = "oaleiloes"
    allowed_domains = ["oaleiloes.com.br"]
    start_urls = ["https://www.oaleiloes.com.br/"]

    def parse(self, response):
        """Home → segue cada `/leilao/{id}` único."""
        seen: set[str] = set()
        for href in response.css("a[href*='/leilao/']::attr(href)").getall():
            if not re.search(r"/leilao/\d+", href):
                continue
            absolute = self.absolute(response, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            yield self.make_request(absolute, callback=self.parse_leilao)

    def parse_leilao(self, response):
        """Leilão → segue cada `/lote/{id}` cuja categoria menciona imóvel."""
        seen: set[str] = set()
        for a in response.css("a[href*='/lote/']"):
            href = a.attrib.get("href")
            if not href or not re.search(r"/lote/\d+", href):
                continue
            absolute = self.absolute(response, href)
            if absolute in seen:
                continue
            anchor_text = " ".join(a.css("::text").getall())
            if not PROPERTY_CATEGORY_RE.search(anchor_text):
                continue
            seen.add(absolute)
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url},
            )

    def parse_property(self, response):
        """Página do lote → emite um `PropertyItem`."""
        loader = self.new_loader(response)

        # Title sai como "OALeilões | <ENDEREÇO> em <CIDADE> - <ESTADO>".
        # Mantemos só a parte após o pipe.
        title = (response.css("title::text").get() or "").strip()
        if "|" in title:
            title = title.split("|", 1)[1].strip()
        loader.add_value("title", title)

        # Texto do body sem ruído (collapse_ws faz no input processor).
        body_text = " ".join(response.css("body *::text").getall())
        body_text = " ".join(body_text.split())

        # A descrição rica do imóvel começa no padrão 'UF/CIDADE. <logradouro>'
        # — antes disso é só nav/header, e o filtro de categoria do nav contém
        # 'loja/galpão/sala comercial' que poluiriam o detect_property_type.
        # 'QUADRA/QD/LOTE/LT' cobrem o padrão DF/GO/Brasília; 'CONJUNTO' aparece
        # em conjuntos habitacionais; resto cobre logradouros tradicionais.
        desc_anchor = re.search(
            r"\b[A-Z]{2}\s*/\s*[A-ZÀ-Ý][A-ZÀ-Ý\s]+\.\s*"
            r"(?:RUA|AV|AVENIDA|ROD|RODOVIA|TRAV|ALAMEDA|EST|ESTRADA|"
            r"QUADRA|QD|LOTE|LT|CONJUNTO|SETOR|VILA|FAZENDA|SITIO|S[IÍ]TIO)",
            body_text,
        )
        if desc_anchor:
            description_block = body_text[desc_anchor.start():desc_anchor.start() + 1500]
        else:
            description_block = body_text[:1500]
        loader.add_value("description", description_block)

        # property_type: SÓ alimentamos do bloco descritivo quando ele veio do
        # desc_anchor (i.e., texto do imóvel, não do nav). Caso contrário cai
        # apenas para o título — preferindo None a "comercial" via "loja" do nav.
        if desc_anchor:
            loader.add_value("property_type", description_block)
        loader.add_value("property_type", title)

        # Preços: rótulos "Avaliação" e "Lance Mínimo" precedem o R$.
        avaliacao = self.first_match(r"Avalia[cç][aã]o:?\s*(R\$\s*[\d.,]+)", body_text)
        lance = self.first_match(r"Lance\s+M[ií]nimo:?\s*(R\$\s*[\d.,]+)", body_text)
        if avaliacao:
            loader.add_value("market_value", avaliacao)
        if lance:
            loader.add_value("minimum_bid", lance)

        # Endereço: 'AL/MACEIO. RUA X, N. 100, ...'
        m = ADDRESS_RE.search(body_text)
        if m:
            uf = m.group(1)
            city = m.group(2).strip().title()
            street_part = m.group(3).strip().rstrip(",.")
            loader.add_value("address", {
                "street": street_part[:240],
                "number": "",
                "complement": "",
                "neighborhood": "",
                "city": city,
                "state": normalize_uf(uf),
                "zip": "",
            })

        # Áreas: 'X M2 DE ÁREA PRIVATIVA' / 'Y M2 DE ÁREA DO TERRENO'
        priv = self.first_match(r"([\d.,]+)\s*M2\s*DE\s*[ÁA]REA\s+PRIVATIVA", body_text)
        terr = self.first_match(r"([\d.,]+)\s*M2\s*DE\s*[ÁA]REA\s+(?:DO\s+)?TERRENO", body_text)
        if priv:
            loader.add_value("area_sqm", priv)
        if terr:
            loader.add_value("total_area_sqm", terr)

        # Quartos / banheiros: 'N QTS', 'N WCS'
        qts = self.first_match(r"(\d+)\s*QT", body_text)
        wcs = self.first_match(r"(\d+)\s*WC", body_text)
        vagas = self.first_match(r"(\d+)\s*VAGAS?", body_text)
        if qts:
            loader.add_value("bedrooms", qts)
        if wcs:
            loader.add_value("bathrooms", wcs)
        if vagas:
            loader.add_value("parking_spots", vagas)

        # Imagens — só fotos do bem (path contém 'bem_foto').
        seen_imgs: set[str] = set()
        images: list[str] = []
        for src in response.css("img::attr(src), img::attr(data-src)").getall():
            if "bem_foto" not in src.lower():
                continue
            absolute = self.absolute(response, src)
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            images.append(absolute)
        if images:
            loader.add_value("images", images)

        # Documentos: PDFs ou âncoras com "edital"/"matrícula" no texto.
        docs: list[dict[str, str]] = []
        for a in response.css("a[href]"):
            href = a.attrib.get("href") or ""
            if not href:
                continue
            text = " ".join(a.css("::text").getall()).strip()
            href_low = href.lower()
            text_low = text.lower()
            if href_low.endswith(".pdf") or "edital" in href_low or "edital" in text_low or "matr" in text_low:
                docs.append({"name": text[:120] or "documento", "url": self.absolute(response, href)})
        if docs:
            loader.add_value("documents", docs)

        loader.add_value("scraped_at", self.now_iso())
        yield loader.load_item()
