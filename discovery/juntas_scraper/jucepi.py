"""JUCEPI — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucepi(StubJuntaScraper):
    sigla = "JUCEPI"
    uf = "PI"
    base_url = "https://www.jucepi.pi.gov.br"
    reason = (
        "requires_manual_request: JUCEPI publica calendário e editais; sem listagem aberta de leiloeiros."
    )
