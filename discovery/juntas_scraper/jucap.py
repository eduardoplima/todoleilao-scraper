"""JUCAP — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucap(StubJuntaScraper):
    sigla = "JUCAP"
    uf = "AP"
    base_url = "https://www.jucap.ap.gov.br"
    reason = (
        "requires_manual_request: JUCAP publica calendário/editais; sem rota /leiloeiros."
    )
