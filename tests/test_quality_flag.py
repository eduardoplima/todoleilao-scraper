"""Testes do helper `_compute_quality_flag` em pipelines_supabase.

A regra atual flagga `suspicious_bid_low_ratio` quando `minimum_bid <
10% * appraisal_value` em lotes com avaliação > R$ 100k. Lotes legítimos
(50% de desconto em 2ª praça, sem avaliação, ou de baixíssimo valor)
passam sem flag.
"""
from __future__ import annotations

from decimal import Decimal

from leilao_scraper.pipelines_supabase import _compute_quality_flag


def test_lance_muito_abaixo_da_avaliacao_é_suspeito():
    # caso real: lote alfa 9733 antes do fix (mb=24k, app=12M)
    flag = _compute_quality_flag(Decimal("24000"), Decimal("12028160.82"))
    assert flag == "suspicious_bid_low_ratio"


def test_lance_50pct_da_avaliacao_é_legitimo():
    # 2ª praça típica: 50% da avaliação
    flag = _compute_quality_flag(Decimal("6014080.41"), Decimal("12028160.82"))
    assert flag is None


def test_lance_10pct_exato_é_legitimo():
    # borda: 10% exato não é suspeito (apenas estritamente abaixo)
    flag = _compute_quality_flag(Decimal("1000"), Decimal("10000"))
    assert flag is None  # 1000 == 10% de 10000 e appraisal < piso


def test_appraisal_abaixo_do_piso_nao_é_flaggado():
    # imóvel barato (R$ 50k) com lance de R$ 100: improvável mas não
    # capturamos — risco/recompensa de falso positivo é baixo.
    flag = _compute_quality_flag(Decimal("100"), Decimal("50000"))
    assert flag is None


def test_sem_minimum_bid_nao_é_flaggado():
    flag = _compute_quality_flag(None, Decimal("1000000"))
    assert flag is None


def test_sem_appraisal_nao_é_flaggado():
    # Sem âncora pra comparar — não dá pra julgar.
    flag = _compute_quality_flag(Decimal("100"), None)
    assert flag is None


def test_minimum_bid_zero_nao_é_flaggado():
    flag = _compute_quality_flag(Decimal("0"), Decimal("1000000"))
    assert flag is None
