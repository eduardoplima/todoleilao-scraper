"""Helpers reutilizados pelos spiders específicos de `proprio_html`.

Concentra:
  - regex adicionais (Primeiro/Segundo Leilão, "Lance Inicial - R$",
    avaliação inline em descrição);
  - função de pós-processamento que aplica os ajustes mais comuns sobre
    um item já carregado pelo `parse_property` do genérico;
  - blacklist de paths que o `_LOT_PATH_PATTERNS` universal aceita por
    engano (`/texto.aspx`, `/lotes/<id>` paginação, etc.);
  - `_uf_from_url_slug` — extrai UF das 27 siglas brasileiras a partir
    do path da URL (tokens `-XX` no slug).
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from leilao_scraper.spiders.soleon import _brl_to_decimal


# ---------------------------------------------------------------------------
# Extração de UF a partir do slug da URL
# ---------------------------------------------------------------------------

_BR_UFS = frozenset({
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG",
    "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR",
    "RS", "SC", "SE", "SP", "TO",
})

_UF_SLUG_RE = re.compile(r"-([a-z]{2})(?:[-/]|$)")


def _uf_from_url_slug(url: str) -> str | None:
    """Extrai UF do path do slug da URL.

    Procura tokens `-XX` no path da URL (não no hostname) onde XX é uma
    das 27 siglas brasileiras. Retorna a ÚLTIMA correspondência válida
    (posição mais próxima do fim do slug — geralmente a UF do lote).
    Retorna None se não encontrar nada.
    """
    try:
        path = urlparse(url).path.lower()
    except Exception:
        path = url.lower()
    found: list[str] = []
    for m in _UF_SLUG_RE.finditer(path):
        candidate = m.group(1).upper()
        if candidate in _BR_UFS:
            found.append(candidate)
    return found[-1] if found else None


# ---------------------------------------------------------------------------
# Regex extras
# ---------------------------------------------------------------------------

# "Primeiro Leilão: R$ 23.000,00" — usado pela plataforma Casa Do Leilão
_RE_PRIMEIRO_LEILAO = re.compile(
    r"Primeiro\s+Leil[ãa]o[:\s]*R\$\s*([\d.,]+)", re.I,
)
_RE_SEGUNDO_LEILAO = re.compile(
    r"Segundo\s+Leil[ãa]o[:\s]*R\$\s*([\d.,]+)", re.I,
)

# "Avaliação: R$ X" (com `:`) — variante usada por Marques Barreto e Casa
_RE_AVALIACAO_INLINE = re.compile(
    r"\bAvalia[çc][ãa]o[:\s]*R\$\s*([\d.,]+)", re.I,
)

# "Lance Mínimo: R$ X" — variante Marques Barreto/Casa (sem prefixo)
_RE_LANCE_MIN_LOOSE = re.compile(
    r"Lance\s+M[íi]nimo[:\s]*R\$\s*([\d.,]+)", re.I,
)

# "Lance Inicial - R$ X" (Biasi)
_RE_LANCE_INICIAL_DASH = re.compile(
    r"Lance\s+Inicial\s*[-–]\s*R\$\s*([\d.,]+)", re.I,
)

# "Lance 1º Leilão R$ X" / "Lance 2º Leilão R$ Y" (Araujo, Portalax)
_RE_LANCE_PRACA_1 = re.compile(
    r"Lance\s+1[ºoº°ªa]\s*Leil[ãa]o\s*R\$\s*([\d.,]+)", re.I,
)
_RE_LANCE_PRACA_2 = re.compile(
    r"Lance\s+2[ºoº°ªa]\s*Leil[ãa]o\s*R\$\s*([\d.,]+)", re.I,
)

# "Avaliação: R$ X" no edital ou rodapé (formatação livre)
_RE_TOTAL_AVALIACAO = re.compile(
    r"TOTAL\s+(?:DA\s+(?:PENHORA\s+E\s+)?AVALIA[ÇC][ÃA]O|AVALIA[ÇC][ÃA]O)"
    r"[:\s]*R\$\s*([\d.,]+)", re.I,
)

# Cidade-UF entre parênteses: "Santo Antônio do Leverger (MT)"
# Não-greedy + lookbehind para palavras "comuns" antes ("cidade de", "município de")
_RE_CIDADE_UF_PAREN = re.compile(
    r"(?:cidade\s+de\s+|munic[íi]pio\s+de\s+|em\s+)?"
    r"([A-ZÀ-Ú][A-Za-zÀ-ú\s.'-]{2,40}?)\s*\(([A-Z]{2})\)",
)

# Cidade-UF "Cidade/UF" (slash explícito) — caso normal
_RE_CIDADE_UF_SLASH = re.compile(
    r"\b([A-ZÀ-Ú][A-Za-zÀ-ú\s.'-]{2,40}?)\s*/\s*([A-Z]{2})\b",
)


# ---------------------------------------------------------------------------
# Path blacklist — URLs que casam padrões universais mas NÃO são lotes
# ---------------------------------------------------------------------------

_NON_LOT_PATH_RE = re.compile(
    r"/texto\.aspx|/contato\.aspx|/parceiros\.aspx|"
    r"/leiloes\.aspx|/leiloes_realizados\.aspx|"
    r"/lotes/\d+(?:[/?]|$)|/login|/cadastr|/portal/?$",
    re.I,
)


def is_non_lot_url(url: str) -> bool:
    """True se `url` for um falso positivo conhecido (info page, listing
    paginação, etc.) que ainda assim passou pelo `_LOT_PATH_PATTERNS` do
    genérico."""
    return bool(_NON_LOT_PATH_RE.search(url))


# ---------------------------------------------------------------------------
# Helpers de extração
# ---------------------------------------------------------------------------

def extract_lance_min_with_dash(body_text: str) -> Decimal | None:
    """Tenta extrair `Lance Inicial - R$ X` / `Lance 2º Leilão R$ X` /
    `Lance 1º Leilão R$ X` na ordem de preferência."""
    for rgx in (_RE_LANCE_PRACA_2, _RE_LANCE_PRACA_1,
                _RE_LANCE_INICIAL_DASH, _RE_LANCE_MIN_LOOSE):
        m = rgx.search(body_text)
        if m:
            try:
                v = _brl_to_decimal(m.group(1))
                if v and v > 0:
                    return v
            except Exception:
                continue
    return None


def extract_casa_platform_prices(body_text: str) -> tuple[Decimal | None, Decimal | None]:
    """Casa Do Leilão / Marques Barreto / Adring:
        `Primeiro Leilão: R$ A` (avaliação efetiva)
        `Segundo Leilão: R$ B` (lance mínimo da 2ª praça)
        OR
        `Avaliação: R$ A` + `Lance Mínimo: R$ B` (Marques)
    Retorna (market_value, minimum_bid) – qualquer um pode ser None.
    """
    market = None
    minimum = None

    m_av = _RE_AVALIACAO_INLINE.search(body_text)
    if m_av:
        try:
            v = _brl_to_decimal(m_av.group(1))
            if v and v > 0:
                market = v
        except Exception:
            pass

    m_first = _RE_PRIMEIRO_LEILAO.search(body_text)
    if m_first:
        try:
            v = _brl_to_decimal(m_first.group(1))
            if v and v > 0:
                # Primeiro Leilão tipicamente == valor de avaliação se vazio
                if market is None:
                    market = v
        except Exception:
            pass

    m_second = _RE_SEGUNDO_LEILAO.search(body_text)
    if m_second:
        try:
            v = _brl_to_decimal(m_second.group(1))
            if v and v > 0:
                minimum = v
        except Exception:
            pass

    if minimum is None:
        m_lm = _RE_LANCE_MIN_LOOSE.search(body_text)
        if m_lm:
            try:
                v = _brl_to_decimal(m_lm.group(1))
                if v and v > 0:
                    minimum = v
            except Exception:
                pass

    if market is None:
        m_tot = _RE_TOTAL_AVALIACAO.search(body_text)
        if m_tot:
            try:
                v = _brl_to_decimal(m_tot.group(1))
                if v and v > 0:
                    market = v
            except Exception:
                pass

    return market, minimum


def extract_cidade_uf(text: str) -> tuple[str, str] | None:
    """Tenta extrair `(cidade, uf)` de uma string livre.

    Estratégia: prefere `Cidade/UF`, fallback para `Cidade (UF)`.
    """
    m = _RE_CIDADE_UF_SLASH.search(text)
    if m:
        cidade = m.group(1).strip().rstrip(",.")
        uf = m.group(2)
        if 3 <= len(cidade) <= 50:
            return cidade, uf
    m = _RE_CIDADE_UF_PAREN.search(text)
    if m:
        cidade = m.group(1).strip().rstrip(",.")
        uf = m.group(2)
        if 3 <= len(cidade) <= 50:
            return cidade, uf
    return None


def collect_pdfs_with_query(response) -> list[dict[str, str]]:
    """Coleta `<a href='*.pdf*'>` — versão tolerante a query string
    (S3 com signed URLs)."""
    docs: list[dict[str, str]] = []
    seen: set[str] = set()
    sel = response.css("a")
    for a in sel:
        href = a.css("::attr(href)").get() or ""
        if ".pdf" not in href.lower():
            continue
        abs_url = response.urljoin(href)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        label = " ".join(t.strip() for t in a.css("*::text").getall() if t.strip())
        docs.append({"name": label[:120] or "documento", "url": abs_url})
    return docs


def collect_bg_images_shorthand(response_text: str) -> list[str]:
    """Captura `background:url(...)` (shorthand CSS) — versão complementar à
    `background-image:` do genérico. Útil para temas que usam shorthand."""
    out: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(
        r"background\s*:\s*url\(['\"]?(https?://[^'\")]+?\.(?:jpe?g|png|webp))",
        response_text, re.I,
    ):
        u = m.group(1)
        low = u.lower()
        if any(skip in low for skip in (
                "logo", "favicon", "icon", "/styles/", "placeholder")):
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def replace_or_add(loader, field: str, value: Any) -> None:
    """Idempotência: substitui o valor do field se já existe, senão adiciona."""
    try:
        loader.replace_value(field, value)
    except Exception:
        loader.add_value(field, value)
