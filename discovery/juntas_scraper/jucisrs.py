"""JUCISRS — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucisrs(StubJuntaScraper):
    sigla = "JUCISRS"
    uf = "RS"
    base_url = "https://jucisrs.rs.gov.br"
    reason = (
        "requires_manual_request: portal JUCISRS exige consulta cadastral autenticada (https/cert issues + sessão)."
    )
