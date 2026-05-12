"""JUCEPA — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucepa(StubJuntaScraper):
    sigla = "JUCEPA"
    uf = "PA"
    base_url = "https://www.jucepa.pa.gov.br"
    reason = (
        "requires_manual_request: JUCEPA usa Drupal sem rota /leiloeiros pública estável."
    )
