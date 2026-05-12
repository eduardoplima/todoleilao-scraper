"""JUCEPE — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucepe(StubJuntaScraper):
    sigla = "JUCEPE"
    uf = "PE"
    base_url = "https://portal.jucepe.pe.gov.br"
    reason = (
        "requires_manual_request: JUCEPE expõe relação apenas via consulta de viabilidade Redesim com captcha."
    )
