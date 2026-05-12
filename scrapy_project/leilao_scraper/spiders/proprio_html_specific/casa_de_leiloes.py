"""Casa de Leilões (www.casadeleiloes.com.br) — 6 lotes na baseline,
**todos falsos positivos**.

Site é um landing page estático ASP.NET que delega o leilão real para
o portal leilovia.com.br via postback JS. Não existem URLs de lote
estáticas neste host — o que o genérico chamava de "lote" eram páginas
`texto.aspx?cod=N&t=...` (informativas) que casaram o padrão
`?(cod|id)=N` do `_LOT_PATH_PATTERNS` universal.

Com a blocklist adicional no genérico (`/texto.aspx`, etc.) este spider
agora descarta os falsos positivos. O resultado correto é **zero lotes**
neste host — a extração real precisa rodar no leilovia.com.br.

# noop spider — genérico (após blocklist) já é correto; baseline era
# 6 falsos positivos. Real estate aqui fica para um spider futuro do
# provider `leilovia`.
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider


class CasaDeLeiloesSpider(ProprioHtmlSpider):
    name = "casa_de_leiloes"
    provider_slug = "casa_de_leiloes"
    auctioneer_slug = "casa_de_leiloes"
