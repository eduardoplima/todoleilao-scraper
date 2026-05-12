"""JUCETINS — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucetins(StubJuntaScraper):
    sigla = "JUCETINS"
    uf = "TO"
    base_url = "https://www.jucetins.to.gov.br"
    reason = (
        "requires_manual_request: JUCETINS expõe lista apenas via consulta Redesim autenticada."
    )
