"""JUCEES — Junta Comercial do Estado do Espírito Santo.

Portal `https://leiloeiros.jucees.es.gov.br/leiloeiros` expõe a lista server-side
em texto bem estruturado por bloco::

    matricula: 002/1976
    Nome: DJANIR DA RÓS
    Endereço: …
    E-mail: …
    Telefone(s): …
    Site: …

A página principal já vem com `regular` ativado por default (filtro). Para
incluir também irregulares poderia-se cruzar com o filtro adicional, mas
nesta v1 retornamos a listagem default.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from .base import JuntaScraper

LISTING_URL = "https://leiloeiros.jucees.es.gov.br/leiloeiros"

MATRICULA_RE = re.compile(r"^matricula:\s*(?P<matricula>[\w/.\-]+)\s*$", re.IGNORECASE)
NOME_RE = re.compile(r"^Nome:\s*(?P<nome>.+?)\s*$", re.IGNORECASE)


class Jucees(JuntaScraper):
    sigla = "JUCEES"
    uf = "ES"
    base_url = "https://leiloeiros.jucees.es.gov.br"

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
            # Próxima linha "Nome: …"
            nome = ""
            for j in range(i + 1, min(i + 5, len(lines))):
                nm = NOME_RE.match(lines[j])
                if nm:
                    nome = nm.group("nome").strip()
                    break
            if not nome:
                continue
            records.append(
                self.record(nome=nome, matricula=matricula, situacao="regular"),
            )

        logger.info("[{}] {} leiloeiros extraídos", self.sigla, len(records))
        return records
