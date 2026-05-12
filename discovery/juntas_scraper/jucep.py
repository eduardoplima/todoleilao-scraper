"""JUCEP — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucep(StubJuntaScraper):
    sigla = "JUCEP"
    uf = "PB"
    base_url = "https://jucep.pb.gov.br"
    reason = (
        "requires_manual_request: JUCEP migrou para portal Redesim — listagem só por consulta autenticada."
    )
