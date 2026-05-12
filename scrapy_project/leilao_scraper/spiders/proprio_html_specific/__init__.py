"""Spiders especializados para os 14 hosts produtivos do `proprio_html`
genérico + portalzuk (maior portal residencial do Brasil).

Cada spider herda de `ProprioHtmlSpider` e sobrescreve **apenas** os
pontos onde a heurística universal erra. O genérico continua sendo a
implementação de referência — estes spiders são otimizações cirúrgicas
para os hosts onde já provamos que há lotes a extrair.

Cobertura (baseline da última run com `proprio_html`):
    - araujoleiloes.com.br (78 lotes)
    - www.alfaleiloes.com (14)
    - www.lucianleiloes.com.br (12)
    - www.casadoleilao.com (11)
    - www.biasileiloes.com.br (10)
    - www.casadeleiloes.com.br (6)
    - www.leiloesonlinems.com.br (5)
    - portalax.com.br (4)
    - www.reginaaudeleiloes.com.br (3)
    - www.lorranaleiloes.com.br (3)
    - www.leonardoveigaleiloes.com.br (3)
    - www.leiloesnovaserrana.com.br (3)
    - www.adringleiloes.com.br (3)
    - www.marquesbarretoleiloes.com.br (1)
    - www.portalzuk.com.br (NOVO — antes `desconhecido`)
"""
