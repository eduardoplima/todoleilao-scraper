"""JCDF — Junta Comercial — stub.

Esta Junta não expõe a relação de leiloeiros em HTML estruturado / sem
captcha. Stub registrado para que o registry conheça a sigla e o runner
relate o status como `requires_manual_request`.
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jcdf(StubJuntaScraper):
    sigla = "JCDF"
    uf = "DF"
    base_url = "https://jcdf.desenvolvimento.gov.br"
    reason = (
        "requires_manual_request: JCDF migrou para subdomínio MDIC; rota nova de leiloeiros ainda não estável."
    )
