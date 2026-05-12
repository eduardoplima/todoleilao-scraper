"""JUCEA — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucea(StubJuntaScraper):
    sigla = "JUCEA"
    uf = "AM"
    base_url = "https://www.jucea.am.gov.br"
    reason = (
        "requires_manual_request: JUCEA publica apenas editais e instruções — sem listagem pública."
    )
