"""JUCEPAR — Junta Comercial do Paraná.

Página única `https://www.juntacomercial.pr.gov.br/Pagina/LEILOEIROS-OFICIAIS-HABILITADOS`
lista todos os leiloeiros oficiais em divs `collapsible-item` (Drupal default).
Cada div tem um heading `NOME | Matrícula: 21/329-L | Data: 02/08/2021` e um
corpo com endereço/contato. Situação (REGULAR/IRREGULAR) vem na string "SITUAÇÃO:".
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from .base import JuntaScraper

LISTING_URL = "https://www.juntacomercial.pr.gov.br/Pagina/LEILOEIROS-OFICIAIS-HABILITADOS"

# "NOME COMPLETO | Matrícula: 21/329-L | Data: dd/mm/yyyy"
HEADING_RE = re.compile(
    r"^(?P<nome>.+?)\s*\|\s*Matr[ií]cula:\s*(?P<matricula>\S+)\s*\|\s*Data:",
    re.IGNORECASE,
)
SITUACAO_RE = re.compile(r"SITUA[ÇC][ÃA]O\s*:\s*([A-ZÇÃÁÉÍÓÚÂÊÔ]+)", re.IGNORECASE)


class JucepaR(JuntaScraper):
    sigla = "JUCEPAR"
    uf = "PR"
    base_url = "https://www.juntacomercial.pr.gov.br"

    def fetch_leiloeiros(self) -> list[dict[str, Any]]:
        response = self.get(LISTING_URL)
        soup = BeautifulSoup(response.text, "lxml")

        records: list[dict[str, Any]] = []
        for panel in soup.select("div.collapsible-item.panel.panel-default"):
            heading = panel.select_one(".collapsible-item-heading, .panel-heading")
            body = panel.select_one(".collapsible-item-body, .panel-body, .panel-collapse")
            heading_text = (heading.get_text(" ", strip=True) if heading else "").strip()
            body_text = (body.get_text(" ", strip=True) if body else "").strip()

            m = HEADING_RE.search(heading_text)
            if not m:
                continue
            nome = m.group("nome").strip()
            matricula = m.group("matricula").strip()

            situacao_match = SITUACAO_RE.search(body_text) or SITUACAO_RE.search(heading_text)
            situacao = situacao_match.group(1).strip().lower() if situacao_match else "regular"

            records.append(
                self.record(nome=nome, matricula=matricula, situacao=situacao),
            )

        logger.info("[{}] {} leiloeiros extraídos", self.sigla, len(records))
        return records
