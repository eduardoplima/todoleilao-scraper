"""Regression tests for AlfaLeiloesSpider price extraction.

Bug observed in prod (May 2026): vários lotes alfa apareciam com
`minimum_bid` ~ R$ 20.000 quando o lance mínimo legal era R$ milhões
(50% da avaliação). Causa: o regex genérico de `proprio_html` casava
o `LANCE MÍNIMO` de cards de *outros* lotes no carrossel "lotes
relacionados" antes do bloco principal do lote, principalmente após
Playwright renderizar o widget Vue `<lote-lance>`.

Estes testes carregam HTML real capturado e garantem que o spider
extrai os valores do bloco `div.lote-wrapper` (escopo certo).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from leilao_scraper.spiders.proprio_html_specific.alfa_leiloes import (
    AlfaLeiloesSpider,
)
from scrapy.http import HtmlResponse, Request

FIXTURES = Path(__file__).parent / "fixtures" / "alfa_leiloes"


def _response(filename: str, url: str) -> HtmlResponse:
    body = (FIXTURES / filename).read_bytes()
    request = Request(url=url, meta={"host": "www.alfaleiloes.com"})
    return HtmlResponse(url=url, body=body, encoding="utf-8", request=request)


@pytest.fixture
def spider():
    return AlfaLeiloesSpider()


def _first_item(spider, response):
    items = [it for it in spider.parse_property(response)
             if isinstance(it, dict) or hasattr(it, "get") and it.get("url")]
    assert items, "parse_property não emitiu item"
    return items[0]


def test_lote_9733_extrai_lance_minimo_correto(spider):
    """Lote 9733 (sítio Guararema): avaliação R$ 12.028.160,82,
    lance mínimo R$ 6.014.080,41. DB tinha R$ 24.000 (card relacionado)."""
    response = _response(
        "lote_9733_sitio_guararema.html",
        "https://www.alfaleiloes.com/lote/9733/leilao-de-sitio-em-guararema-sp/",
    )
    item = _first_item(spider, response)
    assert Decimal(item["market_value"]) == Decimal("12028160.82")
    assert Decimal(item["minimum_bid"]) == Decimal("6014080.41")


def test_lote_9264_extrai_lance_minimo_correto(spider):
    """Lote 9264 (fazenda Paranatinga): avaliação R$ 8.259.401,97,
    lance mínimo R$ 3.303.760,78. DB tinha R$ 20.400 (card relacionado)."""
    response = _response(
        "lote_9264_fazenda_paranatinga.html",
        "https://www.alfaleiloes.com/lote/9264/leilao-de-fazenda-em-paranatinga-mt/",
    )
    item = _first_item(spider, response)
    assert Decimal(item["market_value"]) == Decimal("8259401.97")
    assert Decimal(item["minimum_bid"]) == Decimal("3303760.78")


def test_lote_9733_sob_render_parcial_nao_pega_card_relacionado(spider):
    """Estado de render parcial (div.lote-wrapper ainda não hidratada
    pelo Vue, mas cards-de-lotes-relacionados já com R$ formatado):
    spider NÃO deve pegar `Lance Mínimo: R$ 24.000` de um card lateral.
    Aceita: ausência de minimum_bid, OU minimum_bid igual ao valor
    correto se outra fonte do mesmo lote estiver disponível. NUNCA aceita
    valores de outros lotes."""
    response = _response(
        "lote_9733_broken_render.html",
        "https://www.alfaleiloes.com/lote/9733/leilao-de-sitio-em-guararema-sp/",
    )
    item = _first_item(spider, response)
    mb = item.get("minimum_bid")
    # Sem lote-wrapper, valores de cards relacionados (24.000, 20.400, etc.)
    # NÃO podem vazar para o item principal.
    proibidos = {Decimal("24000"), Decimal("24000.00"), Decimal("20400"),
                 Decimal("20400.00"), Decimal("84042.52"), Decimal("1600")}
    if mb is not None:
        assert Decimal(mb) not in proibidos, (
            f"minimum_bid {mb} veio de card de outro lote — bug regressou"
        )
