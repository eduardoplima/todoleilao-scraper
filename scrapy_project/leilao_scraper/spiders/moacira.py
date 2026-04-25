"""Spider para `moacira.lel.br` (Moacira Tegoni Goedert, DF).

================================================================================
ANÁLISE DA FONTE
================================================================================

Plataforma: leiloar / blast!web (mesma usada por oaleiloes.com.br e outros
*.lel.br). robots.txt limpo (Disallow só /arquivos /cgi-bin /arquivos_geral).

TOPOLOGIA
  /                          home — links para /leilao/{id} ativos
  /leilao/{id}               lista N lotes (até 50/página)
  /leilao/{id}/{page_num}    paginação por SEGMENTO DE PATH (não querystring!)
                             ex.: /leilao/730/2, /leilao/730/3 ...
                             querystrings ?page=2, ?p=2 etc. são ignoradas e
                             devolvem a página 1 (testado).
  /lote/{id}/{slug}          detalhe do imóvel

DESCOBERTA DA PAGINAÇÃO
  - Anchors com texto numérico fazem ``<a href="leilao/730/2">2</a>`` etc.
  - ``re.findall(r"leilao/[0-9]+/([0-9]+)", ...)`` no body retorna [2,3,...,10].
  - O número MAIOR é o total de páginas. Iteramos 2..max (página 1 é a URL
    base). Página fora do range responde 200 com a mesma página 1.

LOTES POR PÁGINA
  - Cada página retorna até 50 anchors `<a href="/lote/{id}/{slug}">` + um
    "lote em destaque" repetido (ex.: id 9809) que aparece em todas as páginas.
    Filtramos por dedup (set de URLs já vistas).

FILTRO DE CATEGORIA NO ANCHOR
  - Texto do anchor contém ex.: "IMÓVEIS / IMÓVEIS RESIDENCIAIS 39% DE DESCONTO".
  - Usamos PROPERTY_CATEGORY_RE — qualquer menção a `imov|casa|apartament|...`
    para evitar lotes de veículos/eletrônicos quando misturados.

LOTE / SELETORES
  - Title HTML: "Moacira Leilões |  Casa em <b>ARAPIRACA/AL</b><p>Endereço:..."
    O conteúdo após `|` carrega tipo + cidade/UF; usamos `<title>::text` que
    retorna o texto plano (sem `<b>`).
  - URL slug embute o tipo: `/lote/10763/casa-em-...`, `/lote/.../apartamento-em-...`.
    Mais confiável que parser de descrição — feedeamos para `property_type`.
  - `.destaque` 3 vezes na página com "Avaliação: R$ X", "Lance Inicial: R$ Y",
    "Incremento: R$ Z". Selector limpo e estável.
  - `.col-8.py-3` ou `.col-8` contém o bloco "DESCRIÇÃO COMPLETA <tipo> em
    <CIDADE/UF> Endereço: <log> N. <num> - <bairro> <tipo>, <area> m2 de
    área total, <area> m2 de área privativa, <area>m2 de área do terreno,
    <n> qts, <n> WCs, ..., 1 vaga de garagem. IPTU: ... Matrícula: ...".
  - Imagens: `img` com path contendo `bem_foto` (idem oaleiloes).

PARTICULARIDADES
  - Sem cookies obrigatórios pra ler /leilao/ e /lote/.
  - Sem lazy load por JS (página vem completa via SSR/PHP).
  - Status do lote (ABERTO/SUSPENSO) aparece em badge na listagem;
    extraímos do anchor pai do `/lote/...`.
  - O lote 9809 (demo SUSPENSO) está em todas as páginas como "destaque".

================================================================================
"""
from __future__ import annotations

import re

from leilao_scraper.loaders import normalize_uf

from .base import BaseAuctionSpider

# qualquer menção a categorias imobiliárias no anchor da listagem
PROPERTY_CATEGORY_RE = re.compile(
    r"\b(imov|imóv|apartament|apto|casa|terreno|lote\s+urb|sala\s+coml|"
    r"galp|chacar|sitio|fazenda|loft|cobertura|kitnet|residenc)",
    re.IGNORECASE,
)

# captura o tipo no slug do lote: /lote/10763/casa-em-..., /lote/.../apartamento-em-...
SLUG_TYPE_RE = re.compile(r"/lote/\d+/([a-z]+)-em-", re.IGNORECASE)

# anchors numéricos da paginação: <a href="leilao/{id}/2">2</a>
PAGE_RE_TEMPLATE = r"leilao/{leilao_id}/(\d+)$"


class MoaciraSpider(BaseAuctionSpider):
    name = "moacira"
    auctioneer_slug = "moacira_tegoni_goedert"
    allowed_domains = ["moacira.lel.br"]
    start_urls = ["https://www.moacira.lel.br/"]
    requires_playwright = False

    # ------- listing flow -----------------------------------------------------

    def parse(self, response):
        """Home → segue cada `/leilao/{id}` único."""
        seen: set[str] = set()
        for href in response.css("a[href*='/leilao/']::attr(href)").getall():
            if not re.search(r"/leilao/\d+(?:$|[?#])", href):
                continue
            absolute = self.absolute(response, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            yield self.make_request(absolute, callback=self.parse_listing)

    def parse_listing(self, response, current_page: int = 1):
        """Página de leilão → emite Request para cada lote + paginação."""
        # 1) lotes desta página
        seen: set[str] = set()
        emitted = 0
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
            emitted += 1
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url},
            )

        # 2) paginação — só processa na primeira chamada (page 1) para não
        # disparar discovery em cada página
        if current_page != 1:
            return

        leilao_id = self._leilao_id(response.url)
        if not leilao_id:
            return
        page_re = re.compile(PAGE_RE_TEMPLATE.format(leilao_id=leilao_id))
        page_nums: set[int] = set()
        for href in response.css("a::attr(href)").getall():
            m = page_re.search(href or "")
            if m:
                page_nums.add(int(m.group(1)))
        if not page_nums:
            return
        max_page = max(page_nums)
        self.log_event(
            "listing_paginated",
            leilao_id=leilao_id, lotes_pagina_1=emitted, total_paginas=max_page,
        )
        for n in range(2, max_page + 1):
            yield self.make_request(
                f"https://www.{self.allowed_domains[0]}/leilao/{leilao_id}/{n}",
                callback=self.parse_listing,
                cb_kwargs={"current_page": n},
            )

    @staticmethod
    def _leilao_id(url: str) -> str | None:
        m = re.search(r"/leilao/(\d+)", url)
        return m.group(1) if m else None

    # ------- detail extraction ------------------------------------------------

    def parse_property(self, response):
        """Página de lote → emite UM `PropertyItem`."""
        loader = self.new_loader(response)

        # title — a fonte ÀS VEZES tem `<b>...</b>` literal dentro de <title>
        # (HTML inválido mas tolerado); removemos tags resíduais.
        raw_title = " ".join(response.css("title::text").getall()).strip()
        if "|" in raw_title:
            raw_title = raw_title.split("|", 1)[1]
        title = re.sub(r"<[^>]+>", " ", raw_title).strip()
        loader.add_value("title", title)

        # property_type — mais confiável a partir do slug
        slug_match = SLUG_TYPE_RE.search(response.url)
        if slug_match:
            loader.add_value("property_type", slug_match.group(1))
        loader.add_value("property_type", title)  # fallback

        # description block — `.col-8.py-3` ou `.col-8` contendo "DESCRI"
        description_block = ""
        for el in response.css(".col-8.py-3, .col-8"):
            txt = " ".join(el.css("::text").getall())
            txt = " ".join(txt.split())
            if "DESCRI" in txt.upper():
                description_block = txt
                break
        if description_block:
            loader.add_value("description", description_block[:4000])

        # preços — os 3 valores estão em `.destaque` (Avaliação, Lance Inicial,
        # Incremento). Capturamos pelo rótulo, não pela ordem.
        destaque_text = " ".join(
            " ".join(el.css("::text").getall()) for el in response.css(".destaque")
        )
        destaque_text = " ".join(destaque_text.split())
        avaliacao = self.first_match(
            r"Avalia[cç][aã]o:?\s*(R\$\s*[\d.,]+)", destaque_text
        )
        lance = self.first_match(
            r"Lance\s+(?:Inicial|M[ií]nimo):?\s*(R\$\s*[\d.,]+)", destaque_text
        )
        if avaliacao:
            loader.add_value("market_value", avaliacao)
        if lance:
            loader.add_value("minimum_bid", lance)

        # endereço — formato "Endereço: RUA X N. NUM - BAIRRO" + "<TIPO> em CIDADE/UF"
        # cidade/UF vem antes do "Endereço:" no description block
        m_loc = re.search(
            r"\b(?:em|EM)\s+([A-ZÀ-Ý][\wÀ-ÿ\s/]+?)\s*/\s*([A-Z]{2})\b",
            description_block,
        )
        m_endereco = re.search(
            r"Endere[cç]o:\s*(.+?)(?=\s+\w+,|\s+IPTU|\s+Matr[ií]cula|\s*$)",
            description_block,
        )
        if m_loc:
            city = m_loc.group(1).strip().title()
            uf = m_loc.group(2)
            street = m_endereco.group(1).strip().rstrip(".,") if m_endereco else ""
            loader.add_value("address", {
                "street": street[:240],
                "number": "",
                "complement": "",
                "neighborhood": "",
                "city": city,
                "state": normalize_uf(uf),
                "zip": "",
            })

        # áreas — "X m2 de área (privativa|total|terreno)"
        priv = self.first_match(
            r"([\d.,]+)\s*m[²2]\s*de\s*[áa]rea\s+privativa", description_block
        )
        total = self.first_match(
            r"([\d.,]+)\s*m[²2]\s*de\s*[áa]rea\s+total", description_block
        )
        terreno = self.first_match(
            r"([\d.,]+)\s*m[²2]\s*de\s*[áa]rea\s+do\s+terreno", description_block
        )
        if priv:
            loader.add_value("area_sqm", priv)
        if total or terreno:
            loader.add_value("total_area_sqm", terreno or total)

        # cômodos — "3 qts", "2 WCs", "1 vaga de garagem"
        qts = self.first_match(r"(\d+)\s*qts?\b", description_block)
        wcs = self.first_match(r"(\d+)\s*WC", description_block)
        vagas = self.first_match(r"(\d+)\s*vaga", description_block)
        if qts:
            loader.add_value("bedrooms", qts)
        if wcs:
            loader.add_value("bathrooms", wcs)
        if vagas:
            loader.add_value("parking_spots", vagas)

        # imagens — moacira mistura fotos do `bem_foto` da plataforma com
        # links externos pra `venda-imoveis.caixa.gov.br/fotos/` (vendas CAIXA).
        # Excluímos logos, banners, ícones; aceitamos o resto que parece foto.
        seen_imgs: set[str] = set()
        images: list[str] = []
        EXCLUDED = ("logomarca", "/banner", "/icones/", "/icone-", "favicon")
        for src in response.css("img::attr(src), img::attr(data-src)").getall():
            if not src:
                continue
            src_low = src.lower()
            if any(bad in src_low for bad in EXCLUDED):
                continue
            if not any(ext in src_low for ext in (".jpg", ".jpeg", ".png", ".webp")):
                continue
            absolute = self.absolute(response, src)
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            images.append(absolute)
        if images:
            loader.add_value("images", images)

        loader.add_value("scraped_at", self.now_iso())
        yield loader.load_item()
