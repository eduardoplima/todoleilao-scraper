"""JUCEG — Junta Comercial do Estado de Goiás.

Página `https://goias.gov.br/juceg/leiloeiros/` lista os leiloeiros em texto
livre. O padrão recorrente em cada bloco é::

    JOÃO ALVES BARROS (Matrícula: 007/90 de 29/08/1990) – PREPOSTA: (…) – Situação: REGULAR

O nome vem antes do primeiro parênteses; a matrícula está dentro; a situação
aparece como "Situação: REGULAR" / "IRREGULAR".
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from .base import JuntaScraper

LISTING_URL = "https://goias.gov.br/juceg/leiloeiros/"

ENTRY_RE = re.compile(
    r"^(?P<nome>[A-ZÇÃÁÉÍÓÚÂÊÔÀÄ][A-ZÇÃÁÉÍÓÚÂÊÔÀÄ\s\.\-']+?)\s*"
    r"\(Mat[ií]?cula:\s*(?P<matricula>[\w/.\-]+)\s+de\s+\d{2}/\d{2}/\d{4}\)"
    r".*?(?:Situa[çc][ãa]o\s*:\s*(?P<situacao>[A-Z]+))?",
    re.IGNORECASE,
)


class Juceg(JuntaScraper):
    sigla = "JUCEG"
    uf = "GO"
    base_url = "https://goias.gov.br/juceg"

    def fetch_leiloeiros(self) -> list[dict[str, Any]]:
        response = self.get(LISTING_URL)
        soup = BeautifulSoup(response.text, "lxml")
        text = soup.get_text("\n", strip=True)

        # Em vez de quebrar por linha (parágrafos mesclam várias entradas),
        # aplico regex multilinha sobre o texto inteiro permitindo line breaks.
        text_oneline = re.sub(r"\s+", " ", text)
        # Padrão "NOME (Matrícula: 007/90 de 29/08/1990)" — a data é opcional
        # porque vários blocos só trazem "Matrícula: NNN/AA".
        records: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for m in re.finditer(
            r"([A-ZÇÃÁÉÍÓÚÂÊÔÀ][A-ZÇÃÁÉÍÓÚÂÊÔÀ\s\.\-']+?)\s*"
            r"\(Mat[rt]?[ií]?cula:\s*([\w/.\-]+)(?:\s+de\s+\d{2}/\d{2}/\d{4})?\)"
            r"(?:[^A-Za-z]*Situa[çc][ãa]o\s*:\s*([A-Z]+))?",
            text_oneline,
        ):
            nome = m.group(1).strip(" -–")
            matricula = m.group(2).strip()
            situacao = (m.group(3) or "regular").lower()
            if len(nome.split()) < 2:
                continue
            key = (nome.lower(), matricula)
            if key in seen:
                continue
            seen.add(key)
            records.append(self.record(nome=nome, matricula=matricula, situacao=situacao))

        logger.info("[{}] {} leiloeiros extraídos", self.sigla, len(records))
        return records
