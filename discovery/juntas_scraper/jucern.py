"""JUCERN — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucern(StubJuntaScraper):
    sigla = "JUCERN"
    uf = "RN"
    base_url = "https://www.jucern.rn.gov.br"
    reason = (
        "requires_manual_request: site JUCERN frequentemente offline (HTTPS error); rota de leiloeiros não pública."
    )
