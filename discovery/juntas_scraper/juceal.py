"""JUCEAL — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Juceal(StubJuntaScraper):
    sigla = "JUCEAL"
    uf = "AL"
    base_url = "https://www.juceal.al.gov.br"
    reason = (
        "requires_manual_request: JUCEAL expõe apenas editais; sem listagem aberta de leiloeiros."
    )
