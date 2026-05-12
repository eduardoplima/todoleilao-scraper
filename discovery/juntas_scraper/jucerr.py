"""JUCERR — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucerr(StubJuntaScraper):
    sigla = "JUCERR"
    uf = "RR"
    base_url = "https://jucerr.rr.gov.br"
    reason = (
        "requires_manual_request: JUCERR publica apenas calendário; sem rota aberta de leiloeiros."
    )
