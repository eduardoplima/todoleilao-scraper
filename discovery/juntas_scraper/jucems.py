"""JUCEMS — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucems(StubJuntaScraper):
    sigla = "JUCEMS"
    uf = "MS"
    base_url = "https://www.jucems.ms.gov.br"
    reason = (
        "requires_manual_request: JUCEMS expõe consulta empresarial autenticada; sem listagem aberta de leiloeiros."
    )
