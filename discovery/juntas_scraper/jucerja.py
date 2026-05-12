"""JUCERJA — Junta Comercial do Estado do Rio de Janeiro.

Página `https://www.jucerja.rj.gov.br/AuxiliaresComercio/Leiloeiros` renderiza
todos os leiloeiros server-side em `ul.ats-listaLnks > li.ats-listaLnks-item`.
Cada item tem labels h5/h6 com `Leiloeiro:`, `Situação Funcional:`, `Nº Matrícula:`.
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from .base import JuntaScraper

LISTING_URL = "https://www.jucerja.rj.gov.br/AuxiliaresComercio/Leiloeiros"


def _label_value(item, label: str) -> str:
    """Encontra o `h6` que segue um `h5` com texto começando por `label`."""
    for h5 in item.find_all("h5"):
        if h5.get_text(strip=True).lower().startswith(label.lower()):
            sibling = h5.find_next_sibling("h6")
            if sibling is not None:
                return sibling.get_text(" ", strip=True)
    return ""


class Jucerja(JuntaScraper):
    sigla = "JUCERJA"
    uf = "RJ"
    base_url = "https://www.jucerja.rj.gov.br"

    def fetch_leiloeiros(self) -> list[dict[str, Any]]:
        response = self.get(LISTING_URL)
        soup = BeautifulSoup(response.text, "lxml")

        # Existem várias `ul.ats-listaLnks` na página; só interessa a que está
        # dentro de `div.listagemLeiloeiros`.
        container = soup.select_one("div.listagemLeiloeiros")
        if container is None:
            logger.warning("[{}] container `.listagemLeiloeiros` não encontrado", self.sigla)
            return []

        records: list[dict[str, Any]] = []
        for item in container.select("li.ats-listaLnks-item"):
            nome = _label_value(item, "Leiloeiro")
            matricula = _label_value(item, "Nº Matr")
            situacao = _label_value(item, "Situação Funcional") or "regular"

            if not nome:
                continue
            records.append(self.record(nome=nome, matricula=matricula, situacao=situacao))

        logger.info("[{}] {} leiloeiros extraídos", self.sigla, len(records))
        return records
