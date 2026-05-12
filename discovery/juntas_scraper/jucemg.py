"""JUCEMG — Junta Comercial do Estado de Minas Gerais.

Página `https://jucemg.mg.gov.br/pagina/140/Leiloeiros+Ordem+Alfab%C3%A9tica`
lista os leiloeiros em texto corrido (sem tabela). Cada bloco começa com o
nome em uma linha isolada, seguido de `Matrícula: 1062 de 30/05/2017`.
A "situação" não aparece explicitamente nessa página (Jucemg separa página
específica de matrícula cancelada, em `.../142/...`).
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from .base import JuntaScraper

LISTING_URL = "https://jucemg.mg.gov.br/pagina/140/Leiloeiros+Ordem+Alfab%C3%A9tica"

# Captura "Matrícula: 1062 de 30/05/2017" ou "Matrícula: 1199".
MATRICULA_RE = re.compile(r"^Matr[ií]cula:\s*([\w/.\-]+)(?:\s+de\s+\S+)?\s*$", re.IGNORECASE)


class Jucemg(JuntaScraper):
    sigla = "JUCEMG"
    uf = "MG"
    base_url = "https://jucemg.mg.gov.br"

    def fetch_leiloeiros(self) -> list[dict[str, Any]]:
        response = self.get(LISTING_URL)
        soup = BeautifulSoup(response.text, "lxml")
        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        records: list[dict[str, Any]] = []
        # Estratégia: para cada linha que casa MATRICULA_RE, a linha imediatamente
        # anterior é o nome (heurística estável na página da JUCEMG).
        for i, line in enumerate(lines):
            m = MATRICULA_RE.match(line)
            if not m:
                continue
            if i == 0:
                continue
            nome_candidate = lines[i - 1].strip()
            # Ignora cabeçalhos/títulos óbvios
            if nome_candidate.lower() in {"a a z", "leiloeiros", "matrícula", "matricula"}:
                continue
            # Nome legítimo costuma ter pelo menos 2 palavras e iniciais maiúsculas.
            if len(nome_candidate.split()) < 2:
                continue
            # Remove sufixos editoriais comuns ("(MATRÍCULA SUPLEMENTAR)" etc.)
            nome_clean = re.sub(r"\s*\([^)]*\)\s*$", "", nome_candidate).strip()
            records.append(
                self.record(nome=nome_clean, matricula=m.group(1), situacao="regular"),
            )

        logger.info("[{}] {} leiloeiros extraídos", self.sigla, len(records))
        return records
