"""JUCESP — Junta Comercial do Estado de São Paulo.

A página oficial `https://www.institucional.jucesp.sp.gov.br/tradutores-leiloeiros.html`
expõe apenas formulários e PDFs de requerimento. A lista de leiloeiros
matriculados não está exposta em HTML estruturado — depende de consulta
pública na busca empresarial (com captcha imageReCAPTCHA-like) ou de
solicitação via LAI / e-SIC.

Stub registrado para sinalizar a Junta como pendente. Reabrir quando a JUCESP
publicar a relação em formato aberto (já há histórico de PDF anual).
"""

from __future__ import annotations

from .base import StubJuntaScraper


class Jucesp(StubJuntaScraper):
    sigla = "JUCESP"
    uf = "SP"
    base_url = "https://www.institucional.jucesp.sp.gov.br"
    reason = (
        "requires_manual_request: JUCESP só publica a relação via PDF anual "
        "ou consulta pública com captcha (RFB/eSIC)."
    )
