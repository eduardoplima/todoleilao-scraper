"""JUCEB — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Juceb(StubJuntaScraper):
    sigla = "JUCEB"
    uf = "BA"
    base_url = "https://www.ba.gov.br/juceb"
    reason = (
        "requires_manual_request: JUCEB consolidou no portal estadual; sem rota /leiloeiros pública."
    )
