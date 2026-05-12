"""JUCESC — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucesc(StubJuntaScraper):
    sigla = "JUCESC"
    uf = "SC"
    base_url = "https://leiloeiros.jucesc.sc.gov.br"
    reason = (
        "requires_manual_request: portal de leiloeiros da JUCESC depende de SPA/iframe legado (Central de Leiloeiro) — fora do escopo de httpx puro."
    )
