"""JUCESE — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucese(StubJuntaScraper):
    sigla = "JUCESE"
    uf = "SE"
    base_url = "https://www.jucese.se.gov.br"
    reason = (
        "requires_manual_request: JUCESE publica apenas calendário de prova e editais — sem listagem aberta."
    )
