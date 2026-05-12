"""JUCEC — Junta Comercial do Estado do Ceará.

Página `https://www.jucec.ce.gov.br/leiloeiros/` (WordPress estático) lista
os leiloeiros em texto livre, com blocos no padrão::

    Matrícula - 01 22/08/1984
    Fernando Montenegro Castelo
    Site: …
    E-mail: …
    Telefone: …
    Endereço …

A "situação" não é explicitada — entradas listadas aqui são todos regulares.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from .base import JuntaScraper

LISTING_URL = "https://www.jucec.ce.gov.br/leiloeiros/"

# "Matrícula - 01 22/08/1984" ou "Matrícula - 22 02/08/2020" — número + data.
MATRICULA_RE = re.compile(
    r"^Matr[ií]cula\s*-\s*(?P<matricula>\d+)(?:\s*(?P<data>\d{2}/\d{2}/\d{4}))?\s*$",
    re.IGNORECASE,
)


class Jucec(JuntaScraper):
    sigla = "JUCEC"
    uf = "CE"
    base_url = "https://www.jucec.ce.gov.br"

    def fetch_leiloeiros(self) -> list[dict[str, Any]]:
        response = self.get(LISTING_URL)
        soup = BeautifulSoup(response.text, "lxml")
        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        records: list[dict[str, Any]] = []
        for i, line in enumerate(lines):
            m = MATRICULA_RE.match(line)
            if not m:
                continue
            matricula = m.group("matricula")
            # Próxima linha é o nome — se a matrícula veio sem data, a data fica
            # na linha seguinte e o nome só depois disso (variação na fonte).
            offset = 1
            nxt = lines[i + offset] if i + offset < len(lines) else ""
            if re.match(r"^\d{2}/\d{2}/\d{4}$", nxt):
                offset += 1
                nxt = lines[i + offset] if i + offset < len(lines) else ""
            nome = nxt.strip()
            if not nome or len(nome.split()) < 2:
                continue
            # Ignora chamadas de tabela e descritores
            if nome.lower() in {"nome", "contato", "endereço", "endereco"}:
                continue
            records.append(
                self.record(nome=nome, matricula=matricula, situacao="regular"),
            )

        logger.info("[{}] {} leiloeiros extraídos", self.sigla, len(records))
        return records
