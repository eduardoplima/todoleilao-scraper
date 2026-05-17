"""Regression tests for SchulmannLeiloesSpider.

Bug original (Mai/2026): genérico `ProprioHtmlSpider` dropava 100% dos
lotes do schulmannleiloes.com.br como `ph_lote_dropped_non_imovel`
porque:
  - Template tem dois <h1>: o primeiro é `<h1 class="assistive-text">
    Menu principal</h1>` (a11y), e o título real está no segundo
    `<h1 id="featured-heading">`. O genérico pegava o primeiro.
  - Sem og:title meta. og:desc também vazio.
  - `_detail_is_imovel(title="Menu principal", body[:3000])` retorna
    False — a palavra "IMÓVEL" só aparece a partir do char ~8700.

Fixture-based para garantir que o fix sobrevive ao genérico mudar.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from leilao_scraper.spiders.proprio_html_specific.schulmann_leiloes import (
    SchulmannLeiloesSpider,
)
from scrapy.http import HtmlResponse, Request

FIXTURES = Path(__file__).parent / "fixtures" / "schulmann_leiloes"


def _response(filename: str, url: str) -> HtmlResponse:
    body = (FIXTURES / filename).read_bytes()
    request = Request(url=url, meta={"host": "schulmannleiloes.com.br"})
    return HtmlResponse(url=url, body=body, encoding="utf-8", request=request)


@pytest.fixture
def spider():
    return SchulmannLeiloesSpider(urls="https://schulmannleiloes.com.br/")


def _items_from(spider, response):
    """parse_property é generator: filtra Items (dict-like) — descarta
    Requests follow-up de edital."""
    out = []
    for r in spider.parse_property(response):
        if not isinstance(r, Request):
            out.append(r)
    return out


def test_lote_5240_sala_central_extrai_titulo_correto(spider):
    """Lote 5240 (Sala Edif. Central 15): título do h1 real, NÃO 'Menu
    principal'. Lance mínimo R$ 55.100 ('A partir de'), avaliação
    R$ 110.000."""
    response = _response(
        "lote_5240_sala_central15.html",
        "https://schulmannleiloes.com.br/detalhe.php?id=5240&imovel=SALA-NO-EDIF.-CENTRAL15",
    )
    items = _items_from(spider, response)
    assert items, "Schulmann lote 5240 deveria extrair imóvel (não dropar)"
    item = items[0]
    assert item.get("title"), "Título não pode estar vazio"
    title = item["title"]
    assert "Menu principal" not in title, f"título errado: {title!r}"
    assert "CENTRAL" in title.upper() or "SALA" in title.upper(), title
    # Avaliação Total: R$ 110.000,00 (ou primeira do edital — 55.100/55.000)
    if item.get("market_value"):
        assert Decimal(item["market_value"]) > Decimal("0")
    if item.get("minimum_bid"):
        assert Decimal(item["minimum_bid"]) > Decimal("0")
    # UF default RJ
    addr = item.get("address") or {}
    assert addr.get("uf") == "RJ"


def test_lote_5804_angra_extrai_dados(spider):
    """Lote 5804 (imóvel em Angra dos Reis)."""
    response = _response(
        "lote_5804_angra_dos_reis.html",
        "https://schulmannleiloes.com.br/detalhe.php?id=5804&imovel=IM%C3%93VEL-EM-ANGRA-DOS-REIS",
    )
    items = _items_from(spider, response)
    assert items, "Schulmann 5804 (Angra) deveria extrair"
    item = items[0]
    assert "IMÓVEL" in (item.get("title") or "").upper() or \
           "ANGRA" in (item.get("title") or "").upper()
    assert item["status"] == "aberto"


def test_lote_6393_semirreboque_drop(spider):
    """Lote 6393 é Semirreboque (veículo) — DEVE ser dropado.
    Garantia que o spider não vaza veículos como imóveis."""
    response = _response(
        "lote_6393_semirreboque_dropped.html",
        "https://schulmannleiloes.com.br/detalhe.php?id=6393&imovel=Semirreboque-tanque-marca",
    )
    items = _items_from(spider, response)
    assert items == [], (
        f"Lote 6393 (Semirreboque) NÃO pode emitir item — "
        f"é veículo. Emitiu: {[i.get('title') for i in items]}"
    )


def test_source_lot_code_extraction(spider):
    """source_lot_code deve ser o N do `?id=N`."""
    response = _response(
        "lote_5240_sala_central15.html",
        "https://schulmannleiloes.com.br/detalhe.php?id=5240&imovel=SALA-NO-EDIF.-CENTRAL15",
    )
    items = _items_from(spider, response)
    assert items
    assert items[0].get("source_lot_code") == "5240"
