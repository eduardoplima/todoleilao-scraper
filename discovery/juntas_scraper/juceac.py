"""JUCEAC — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Juceac(StubJuntaScraper):
    sigla = "JUCEAC"
    uf = "AC"
    base_url = "https://juceac.ac.gov.br"
    reason = (
        "requires_manual_request: JUCEAC publica calendário e editais; sem listagem aberta."
    )
