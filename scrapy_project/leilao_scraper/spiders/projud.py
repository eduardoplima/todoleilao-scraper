"""Spider para `projudleiloes.com.br` — PRÓ-JUD Leilões (SP, Carlos Campanhã).

================================================================================
ANÁLISE — XHR-FIRST (per orientação do prompt 16)
================================================================================

A página `/imoveis` e `/leilao/<slug>/<id>/` são SPAs jQuery — o HTML inicial
não contém anchors `/lote/` (`static_useful_links=0` no site_analysis.csv;
classificado como `dynamic`).

Capturei XHRs com Playwright (descritivo abaixo, NÃO no fluxo do spider —
playwright só serviu pra recon manual):

  POST /ApiEngine/GetLotesLeilao/{leilao_id}/{page}/{?}/{?}    → JSON 200
  POST /api/GetMenu                                            → categorias
  POST /api/GetAoVivo/{leilao_id}                              → real-time
  POST /api/GetLogin                                           → auth state
  WS  /LancesHub/negotiate                                     → SignalR

`GetLotesLeilao` é o jackpot. Body `{}` (literalmente JSON vazio), retorna
`{Lotes: [...], Paginacao: {...}, CountTotal, CountAbertos, ...}`. **Nenhuma
auth necessária**. Cada Lote vem com tudo que precisamos:

  Lote                    → title
  URLlote                 → relative URL (`lote/<slug>/<id>/`)
  IconeCategoria          → "Apartamentos", "Casas", "Terrenos", "Mobiliário"...
  Categoria               → "Residenciais", "Comerciais", "Diversos"...
  Cidade, UF              → endereço
  Lote_CEP, Lote_Endereco → quando preenchidos (raros mesmo em imóveis)
  ValorAvaliacao          → market_value (Decimal direto)
  GetLoteRealTime[0].ProximoLance → minimum_bid
  Fotos[].Foto            → UUID.png; URL final: /imagens/770x540/{Foto}
  PracaAtual              → 1 ou 2; mapeia para `auction_phase`
  Comitente, LabelModalidade → contexto adicional para `description`

→ Decisão: **API direta, sem Playwright** (`requires_playwright = False`).
Mais rápido (~50ms/page), mais estável (sem flakiness do navegador), sem
dependência do Chromium em CI.

================================================================================
LIMITAÇÃO ATUAL — DISCOVERY DE LEILÕES
================================================================================

A API `GetLotesLeilao` precisa de um `leilao_id` específico — não há
endpoint `GetLotes` global filtrável por categoria. Para descobrir os IDs
dinamicamente, seria necessário ou:

  (a) outra API ainda não-mapeada que liste leilões ativos, ou
  (b) Playwright na home `/imoveis` para extrair links `/leilao/<slug>/<id>/`,
      enfileirando-os em seguida pra a API.

V1 (este spider) usa um seed de IDs **conhecidos por terem imóveis** —
descobertos manualmente sondando `1400..1800`. Atualizar quando novos
leilões surgirem ou implementar (b) com `requires_playwright=True`
restrito ao primeiro hop.

================================================================================
"""

from __future__ import annotations

import json
from urllib.parse import urljoin

import scrapy

from leilao_scraper.loaders import normalize_uf

from .base import BaseAuctionSpider

API_BASE = "https://www.projudleiloes.com.br/ApiEngine/GetLotesLeilao"
SITE_BASE = "https://www.projudleiloes.com.br"
PHOTO_BASE = "https://www.projudleiloes.com.br/imagens/770x540"

# IconeCategoria valores que consideramos "imóvel"
PROPERTY_ICON_CATEGORIES = {
    "apartamentos",
    "casas",
    "terrenos",
    "lotes",
    "loteamentos",
    "salas comerciais",
    "salas",
    "lojas",
    "galpões",
    "galpoes",
    "galpao",
    "predios",
    "prédios",
    "comerciais",
    "residenciais",
    "rural",
    "fazendas",
    "sítios",
    "sitios",
    "chácaras",
    "chacaras",
    "imóveis",
    "imoveis",
    "imovel",
}

# Mapa IconeCategoria → nosso property_type canônico
ICON_TO_TYPE = {
    "apartamentos": "apartamento",
    "casas": "casa",
    "terrenos": "terreno",
    "lotes": "terreno",
    "loteamentos": "terreno",
    "salas comerciais": "comercial",
    "salas": "comercial",
    "lojas": "comercial",
    "galpões": "comercial",
    "galpoes": "comercial",
    "galpao": "comercial",
    "predios": "comercial",
    "prédios": "comercial",
    "comerciais": "comercial",
    "rural": "rural",
    "fazendas": "rural",
    "sítios": "rural",
    "sitios": "rural",
    "chácaras": "rural",
    "chacaras": "rural",
}


class ProjudSpider(BaseAuctionSpider):
    name = "projud"
    auctioneer_slug = "projudleiloes"
    allowed_domains = ["projudleiloes.com.br"]
    requires_playwright = False  # API direta, sem JS

    # Seed de leilões conhecidos por terem imóveis. Ver "limitação atual"
    # no docstring — discovery automática é trabalho futuro.
    leilao_seeds: list[int] = [1450]

    custom_settings = {
        # Nosso AutoThrottle padrão é OK; só forçamos POST default no Spider
        # via método start_requests.
    }

    def start_requests(self):
        for leilao_id in self.leilao_seeds:
            yield self._api_request(leilao_id, page=1)

    def _api_request(self, leilao_id: int, page: int) -> scrapy.Request:
        url = f"{API_BASE}/{leilao_id}/{page}/1/0"
        return scrapy.Request(
            url=url,
            method="POST",
            body=b"{}",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            callback=self.parse_api,
            cb_kwargs={"leilao_id": leilao_id, "page": page},
            meta={"dont_redirect": True},
        )

    def parse_api(self, response, leilao_id: int, page: int):
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.log_event(
                "api_parse_error", leilao_id=leilao_id, page=page, body=response.text[:200]
            )
            return

        lotes = data.get("Lotes") or []
        page_index_max = int(data.get("PageIndexMax") or 0)
        if not lotes:
            return

        emitted = 0
        skipped = 0
        for lote in lotes:
            url_relative = lote.get("URLlote") or ""
            url_absolute = urljoin(SITE_BASE + "/", url_relative)
            source_listing = urljoin(SITE_BASE + "/", lote.get("URLleilao") or "")

            icon = (lote.get("IconeCategoria") or "").strip().lower()
            if icon not in PROPERTY_ICON_CATEGORIES:
                skipped += 1
                continue

            # constrói item via new_loader (URL + auctioneer + source pré-preenchidos)
            fake_response = scrapy.http.HtmlResponse(
                url=url_absolute,
                body=b"",
                encoding="utf-8",
                request=scrapy.Request(url_absolute, meta={"source_listing_url": source_listing}),
            )
            loader = self.new_loader(fake_response)

            loader.add_value("title", lote.get("Lote") or "")
            loader.add_value(
                "description",
                self._build_description(lote),
            )

            ptype = ICON_TO_TYPE.get(icon)
            if ptype:
                loader.add_value("property_type", ptype)
            else:
                loader.add_value("property_type", lote.get("Lote") or "")

            # preços
            valor_aval = lote.get("ValorAvaliacao") or 0
            if valor_aval:
                loader.add_value("market_value", str(valor_aval))
            real_time = (lote.get("GetLoteRealTime") or [{}])[0]
            prox_lance = real_time.get("ProximoLance") or 0
            if prox_lance:
                loader.add_value("minimum_bid", str(prox_lance))

            # praça
            praca = lote.get("PracaAtual")
            if praca == 1:
                loader.add_value("auction_phase", "1a_praca")
            elif praca == 2:
                loader.add_value("auction_phase", "2a_praca")

            # status
            if lote.get("IsEncerrado"):
                loader.add_value("status", "arrematado")
            else:
                loader.add_value("status", "aberto")

            # endereço
            cidade = lote.get("Cidade")
            uf = lote.get("UF")
            if cidade or uf:
                loader.add_value(
                    "address",
                    {
                        "street": (lote.get("Lote_Endereco") or "")[:240],
                        "number": str(lote.get("Lote_Numero") or ""),
                        "complement": lote.get("Lote_Complemento") or "",
                        "neighborhood": lote.get("Lote_Bairro") or "",
                        "city": cidade or "",
                        "state": normalize_uf(uf) or "",
                        "zip": lote.get("Lote_CEP") or "",
                    },
                )

            # fotos
            fotos = lote.get("Fotos") or []
            images = [f"{PHOTO_BASE}/{f.get('Foto')}" for f in fotos if f.get("Foto")]
            if images:
                loader.add_value("images", images)

            loader.add_value("scraped_at", self.now_iso())
            yield loader.load_item()
            emitted += 1

        self.log_event(
            "page_processed",
            leilao_id=leilao_id,
            page=page,
            total=len(lotes),
            emitted=emitted,
            skipped_non_property=skipped,
        )

        # próxima página (PageIndexMax é 0-indexed; current page é 1-indexed)
        if page <= page_index_max:
            yield self._api_request(leilao_id, page + 1)

    @staticmethod
    def _build_description(lote: dict) -> str:
        parts = []
        comitente = lote.get("Comitente")
        if comitente:
            parts.append(f"Comitente: {comitente}")
        modalidade = lote.get("LabelModalidade")
        if modalidade:
            parts.append(f"Modalidade: {modalidade}")
        categoria = lote.get("Categoria")
        if categoria:
            parts.append(f"Categoria: {categoria}")
        icon = lote.get("IconeCategoria")
        if icon and icon.lower() != (categoria or "").lower():
            parts.append(f"Tipo: {icon}")
        cidade = lote.get("Cidade")
        uf = lote.get("UF")
        if cidade or uf:
            parts.append(f"Local: {cidade}/{uf}")
        return " | ".join(parts)
