"""Processadores e ItemLoader para `PropertyItem`.

Os processadores são funções puras e exportadas para uso direto:

  - `clean_money("R$ 1.234,56")` → `Decimal('1234.56')`
  - `parse_br_date("15/03/2025 às 14h00")` → `'2025-03-15T14:00:00-03:00'`
  - `normalize_uf("São Paulo")` → `'SP'`
  - `detect_property_type("Apartamento 2 dorm")` → `'apartamento'`
  - `clean_html("<p>foo <b>bar</b></p>")` → `'foo bar'`

`PropertyLoader` aplica os processadores adequados a cada campo do
`PropertyItem`. Para `address` (dict aninhado), a normalização da UF
fica a cargo do spider — tipicamente:
`loader.add_value("address", {"state": normalize_uf(uf), ...})`.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup
from itemloaders.processors import Identity, MapCompose, TakeFirst
from scrapy.loader import ItemLoader

from .items import PropertyItem

TZ_OFFSET = "-03:00"

# ---------------------------------------------------------------------------
# helpers internos
# ---------------------------------------------------------------------------


def _strip_accents(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _collapse_ws(s: str) -> str:
    return " ".join(s.split())


# ---------------------------------------------------------------------------
# valores monetários
# ---------------------------------------------------------------------------

_MONEY_KEEP = re.compile(r"[^\d,.\-]")


def clean_money(value):
    """Converte strings BRL para `Decimal`. Retorna `None` quando inválido.

    Aceita: "R$ 123.456,78", "R$ 1.000", "1234,56", "1234.56", "1.234".
    Distingue separador de milhar de ponto decimal pelo padrão de uso:
    se há "," e "." → "." é milhar, "," é decimal (formato BR completo);
    se há só "," → decimal; se há só "." múltiplos → milhar;
    se há um único "." → mantém (interpretado como decimal US).
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = _MONEY_KEEP.sub("", s)
    if not s or s in {".", ",", "-"}:
        return None

    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    # else: deixa como está — interpreta como Decimal direto

    try:
        return Decimal(s)
    except InvalidOperation:
        return None


# ---------------------------------------------------------------------------
# datas BR
# ---------------------------------------------------------------------------

_DATE_NUMERIC_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_TIME_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:[h:](\d{2})?(?:\s*min)?)",
    re.IGNORECASE,
)
_MONTH_NAMES = {
    "janeiro": 1,
    "jan": 1,
    "fevereiro": 2,
    "fev": 2,
    "marco": 3,
    "mar": 3,
    "abril": 4,
    "abr": 4,
    "maio": 5,
    "mai": 5,
    "junho": 6,
    "jun": 6,
    "julho": 7,
    "jul": 7,
    "agosto": 8,
    "ago": 8,
    "setembro": 9,
    "set": 9,
    "outubro": 10,
    "out": 10,
    "novembro": 11,
    "nov": 11,
    "dezembro": 12,
    "dez": 12,
}
_DATE_TEXT_RE = re.compile(
    r"(\d{1,2})\s+de\s+(\w+)(?:\s+de)?\s+(\d{4})",
    re.IGNORECASE,
)


def parse_br_date(value):
    """'15/03/2025 às 14h00' → '2025-03-15T14:00:00-03:00'.

    Aceita formatos numéricos (`dd/mm/yyyy`, com hora opcional `HHhMM`,
    `HH:MM`) e por extenso (`dd de mes de yyyy`). Retorna `None` quando
    a string não for parsable ou produzir uma data inválida.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    day = month = year = None
    m = _DATE_NUMERIC_RE.search(s)
    if m:
        day, month, year = (int(m.group(i)) for i in (1, 2, 3))
    else:
        m = _DATE_TEXT_RE.search(s)
        if m:
            day = int(m.group(1))
            month_name = _strip_accents(m.group(2)).lower()
            month = _MONTH_NAMES.get(month_name)
            year = int(m.group(3))

    if day is None or month is None or year is None:
        return None

    hour = 0
    minute = 0
    after_date = s[m.end() :] if m else s
    tm = _TIME_RE.search(after_date)
    if tm:
        hour = int(tm.group(1))
        if tm.group(2):
            minute = int(tm.group(2))

    try:
        dt = datetime(year, month, day, hour, minute)
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + TZ_OFFSET


# ---------------------------------------------------------------------------
# UF
# ---------------------------------------------------------------------------

UF_FULL_TO_CODE = {
    "ACRE": "AC",
    "ALAGOAS": "AL",
    "AMAPA": "AP",
    "AMAZONAS": "AM",
    "BAHIA": "BA",
    "CEARA": "CE",
    "DISTRITO FEDERAL": "DF",
    "ESPIRITO SANTO": "ES",
    "GOIAS": "GO",
    "MARANHAO": "MA",
    "MATO GROSSO": "MT",
    "MATO GROSSO DO SUL": "MS",
    "MINAS GERAIS": "MG",
    "PARA": "PA",
    "PARAIBA": "PB",
    "PARANA": "PR",
    "PERNAMBUCO": "PE",
    "PIAUI": "PI",
    "RIO DE JANEIRO": "RJ",
    "RIO GRANDE DO NORTE": "RN",
    "RIO GRANDE DO SUL": "RS",
    "RONDONIA": "RO",
    "RORAIMA": "RR",
    "SANTA CATARINA": "SC",
    "SAO PAULO": "SP",
    "SERGIPE": "SE",
    "TOCANTINS": "TO",
}
_UF_CODES = set(UF_FULL_TO_CODE.values())


def normalize_uf(value):
    """'São Paulo' → 'SP'; 'sp' → 'SP'; 'XX' → None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    upper = _strip_accents(s).upper()
    if upper in _UF_CODES:
        return upper
    return UF_FULL_TO_CODE.get(upper)


# ---------------------------------------------------------------------------
# property_type
# ---------------------------------------------------------------------------

# Ordem importa: primeiro match vence. Categorias mais específicas
# (comercial, rural) vêm antes de "casa"/"terreno" para evitar que
# "Galpão Industrial" caia em "casa" via "casa "/regex.
PROPERTY_TYPE_RULES = (
    ("apartamento", ("apartamento", "apto", "kitnet", "studio", "loft", "flat", "cobertura")),
    (
        "comercial",
        (
            "sala comercial",
            "loja",
            "galpao",
            "imovel comercial",
            "ponto comercial",
            "predio comercial",
        ),
    ),
    ("rural", ("fazenda", "sitio", "chacara", "rural")),
    ("casa", ("casa", "sobrado", "residencia")),
    ("terreno", ("terreno", "lote", "gleba")),
)
_PROP_TYPE_PATTERNS = [
    (label, [re.compile(rf"\b{re.escape(_strip_accents(kw).lower())}\b") for kw in kws])
    for label, kws in PROPERTY_TYPE_RULES
]


def detect_property_type(value):
    """Heurística sobre título/descrição. Retorna `None` quando nenhuma keyword bate."""
    if value is None:
        return None
    text = _strip_accents(str(value)).lower()
    for label, patterns in _PROP_TYPE_PATTERNS:
        for pat in patterns:
            if pat.search(text):
                return label
    return None


# ---------------------------------------------------------------------------
# limpeza de HTML
# ---------------------------------------------------------------------------


def clean_html(value):
    """Remove tags + scripts/styles e colapsa whitespace. Mantém o texto."""
    if value is None:
        return None
    s = str(value)
    if not s.strip():
        return ""
    soup = BeautifulSoup(s, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return _collapse_ws(soup.get_text(separator=" "))


# ---------------------------------------------------------------------------
# ItemLoader
# ---------------------------------------------------------------------------


def _strip(value):
    return value.strip() if isinstance(value, str) else value


def _to_int(value):
    if value is None or value == "":
        return None
    try:
        return int(re.sub(r"[^\d-]", "", str(value)))
    except (ValueError, TypeError):
        return None


def _to_decimal_area(value):
    """Áreas: '120,5 m²' → Decimal('120.5')."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # se vem com R$, é dinheiro — não área
    if "R$" in s:
        return None
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s or s in {".", ",", "-"}:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


class PropertyLoader(ItemLoader):
    """ItemLoader para `PropertyItem`.

    Convenção: spiders alimentam `property_type` várias vezes com candidatos
    (ex.: `add_xpath` no título e na descrição). Como o input processor é
    `detect_property_type`, valores que não baterem viram `None` e são
    descartados pelo `MapCompose`. `TakeFirst` no output devolve o primeiro
    match válido.
    """

    default_item_class = PropertyItem
    default_output_processor = TakeFirst()

    title_in = MapCompose(_strip, _collapse_ws)
    description_in = MapCompose(clean_html)

    minimum_bid_in = MapCompose(clean_money)
    market_value_in = MapCompose(clean_money)

    first_auction_date_in = MapCompose(parse_br_date)
    second_auction_date_in = MapCompose(parse_br_date)

    property_type_in = MapCompose(detect_property_type)

    bedrooms_in = MapCompose(_to_int)
    bathrooms_in = MapCompose(_to_int)
    parking_spots_in = MapCompose(_to_int)

    area_sqm_in = MapCompose(_to_decimal_area)
    total_area_sqm_in = MapCompose(_to_decimal_area)

    # coleções: spider entrega listas; ItemLoader.add_value já expande list/tuple,
    # então Identity preserva a ordem dos elementos sem aninhar.
    images_out = Identity()
    documents_out = Identity()
    # address é um dict único — TakeFirst (default) extrai o dict cru.
