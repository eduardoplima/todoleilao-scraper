"""Testes dos processadores e ItemLoader.

`pythonpath = ["scrapy_project"]` no pyproject.toml expõe `leilao_scraper` para
o import desses testes.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from leilao_scraper.items import PropertyItem
from leilao_scraper.loaders import (
    PropertyLoader,
    clean_html,
    clean_money,
    detect_property_type,
    normalize_uf,
    parse_br_date,
)


# ---------------------------------------------------------------------------
# clean_money
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("R$ 100.000,00", Decimal("100000.00")),
        ("R$ 1.234.567,89", Decimal("1234567.89")),
        ("R$ 100,00", Decimal("100.00")),
        ("R$ 100", Decimal("100")),
        ("1.000.000", Decimal("1000000")),
        ("12345,67", Decimal("12345.67")),
        ("12345.67", Decimal("12345.67")),
        ("  R$  42  ", Decimal("42")),
    ],
)
def test_clean_money_valid(raw, expected):
    assert clean_money(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "abc", "R$", "  ", "."])
def test_clean_money_invalid(raw):
    assert clean_money(raw) is None


# ---------------------------------------------------------------------------
# parse_br_date
# ---------------------------------------------------------------------------

def test_parse_br_date_numeric():
    assert parse_br_date("15/03/2025") == "2025-03-15T00:00:00-03:00"


def test_parse_br_date_with_time_h():
    assert parse_br_date("15/03/2025 às 14h00") == "2025-03-15T14:00:00-03:00"


def test_parse_br_date_with_time_h_no_minutes():
    assert parse_br_date("01/12/2024 14h") == "2024-12-01T14:00:00-03:00"


def test_parse_br_date_with_time_colon():
    assert parse_br_date("01/12/2024 09:30") == "2024-12-01T09:30:00-03:00"


def test_parse_br_date_textual():
    assert parse_br_date("15 de março de 2025") == "2025-03-15T00:00:00-03:00"


def test_parse_br_date_textual_abbrev():
    assert parse_br_date("3 de jan de 2026") == "2026-01-03T00:00:00-03:00"


@pytest.mark.parametrize(
    "raw",
    ["", None, "data inválida", "32/13/2025", "00/00/0000"],
)
def test_parse_br_date_invalid(raw):
    assert parse_br_date(raw) is None


# ---------------------------------------------------------------------------
# normalize_uf
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("São Paulo", "SP"),
        ("sao paulo", "SP"),
        ("SP", "SP"),
        ("sp", "SP"),
        ("Distrito Federal", "DF"),
        ("RIO DE JANEIRO", "RJ"),
        ("Mato Grosso do Sul", "MS"),
        ("Espírito Santo", "ES"),
        ("Goiás", "GO"),
    ],
)
def test_normalize_uf_valid(raw, expected):
    assert normalize_uf(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "XX", "Lisboa", "ZZ"])
def test_normalize_uf_invalid(raw):
    assert normalize_uf(raw) is None


# ---------------------------------------------------------------------------
# detect_property_type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Apartamento 2 dormitórios", "apartamento"),
        ("Cobertura duplex", "apartamento"),
        ("KITNET no centro", "apartamento"),
        ("Casa em condomínio", "casa"),
        ("Sobrado em vila", "casa"),
        ("Terreno com 500m²", "terreno"),
        ("Lote 12", "terreno"),
        ("Galpão industrial", "comercial"),
        ("Sala comercial centro", "comercial"),
        ("Loja em shopping", "comercial"),
        ("Sítio em Atibaia", "rural"),
        ("Fazenda 100ha", "rural"),
    ],
)
def test_detect_property_type_categories(raw, expected):
    assert detect_property_type(raw) == expected


def test_detect_property_type_first_match_wins():
    # "Apartamento na casa nova" — apartamento vem primeiro nas regras
    assert detect_property_type("Apartamento na casa nova") == "apartamento"
    # "Casa em terreno" — casa vem antes de terreno na ordem
    assert detect_property_type("Casa em terreno de 200m²") == "casa"


def test_detect_property_type_specific_before_generic():
    # "Galpão" deve ser comercial, não casa, mesmo que "casa" apareça em
    # outras palavras como "casamento" — por isso usamos word boundary.
    assert detect_property_type("Galpão industrial em Casamentópolis") == "comercial"


def test_detect_property_type_no_match():
    assert detect_property_type("oportunidade incrível") is None
    assert detect_property_type("") is None
    assert detect_property_type(None) is None


# ---------------------------------------------------------------------------
# clean_html
# ---------------------------------------------------------------------------

def test_clean_html_strips_tags():
    assert clean_html("<p>Texto <b>com</b> tags</p>") == "Texto com tags"


def test_clean_html_drops_scripts_and_styles():
    assert clean_html("<style>x{}</style>antes<script>alert(1)</script>depois") == "antes depois"


def test_clean_html_collapses_whitespace():
    assert clean_html("  multiple   \n  spaces  ") == "multiple spaces"


def test_clean_html_empty():
    assert clean_html("") == ""
    assert clean_html(None) is None


def test_clean_html_handles_entities():
    # BeautifulSoup decodifica entities padrão
    assert clean_html("R$&nbsp;100,00") == "R$ 100,00"


# ---------------------------------------------------------------------------
# PropertyLoader integração
# ---------------------------------------------------------------------------

def test_loader_applies_money_processor():
    loader = PropertyLoader(item=PropertyItem())
    loader.add_value("minimum_bid", "R$ 250.000,00")
    loader.add_value("market_value", "R$ 500.000,00")
    item = loader.load_item()
    assert item["minimum_bid"] == Decimal("250000.00")
    assert item["market_value"] == Decimal("500000.00")


def test_loader_applies_date_processor():
    loader = PropertyLoader(item=PropertyItem())
    loader.add_value("first_auction_date", "10/04/2026 às 11h30")
    item = loader.load_item()
    assert item["first_auction_date"] == "2026-04-10T11:30:00-03:00"


def test_loader_property_type_takes_first_valid():
    """Title não bate, description bate — TakeFirst pega o segundo."""
    loader = PropertyLoader(item=PropertyItem())
    loader.add_value("property_type", "Oportunidade incrível")  # → None
    loader.add_value("property_type", "Apartamento 2 dorm")     # → 'apartamento'
    loader.add_value("property_type", "Casa")                   # → 'casa' (descartado)
    item = loader.load_item()
    assert item["property_type"] == "apartamento"


def test_loader_title_collapses_whitespace():
    loader = PropertyLoader(item=PropertyItem())
    loader.add_value("title", "  Apartamento\n  com   2 dorm  ")
    item = loader.load_item()
    assert item["title"] == "Apartamento com 2 dorm"


def test_loader_description_strips_html():
    loader = PropertyLoader(item=PropertyItem())
    loader.add_value("description", "<p>Texto <b>negrito</b></p>")
    item = loader.load_item()
    assert item["description"] == "Texto negrito"


def test_loader_int_fields():
    loader = PropertyLoader(item=PropertyItem())
    loader.add_value("bedrooms", "3 dorm")
    loader.add_value("bathrooms", "2")
    item = loader.load_item()
    assert item["bedrooms"] == 3
    assert item["bathrooms"] == 2


def test_loader_address_passes_through_dict():
    """Address é dict — TakeFirst extrai o dict como dict (não como lista)."""
    loader = PropertyLoader(item=PropertyItem())
    addr = {
        "street": "Rua X",
        "number": "100",
        "city": "São Paulo",
        "state": normalize_uf("São Paulo"),
        "zip": "01310-100",
    }
    loader.add_value("address", addr)
    item = loader.load_item()
    assert item["address"] == addr
    assert item["address"]["state"] == "SP"
