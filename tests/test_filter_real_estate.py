from __future__ import annotations

from discovery.filter_real_estate import classify, score_row, _normalize


def test_normalize_strips_accents():
    assert _normalize("LEILÃO de IMÓVEIS") == "leilao de imoveis"


def test_clear_real_estate_site_high_confidence():
    row = {
        "nome": "Frazão Imóveis Leilões",
        "site_title": "Leilão de Imóveis - Apartamentos e casas",
        "site_description": "Imóveis em leilão judicial e extrajudicial",
        "site_keywords": "imóveis, apartamento, leilão",
        "site_body_excerpt": "Encontre apartamentos, casas e terrenos em praça única.",
        "dominio": "https://example.com",
    }
    out = classify(row)
    assert out["confidence"] == "high"
    assert out["real_estate_score"] >= 8


def test_vehicle_site_no_strong_caps_at_medium():
    """Sem nenhum keyword strong, confidence é capped em medium — mesmo com score alto."""
    row = {
        "nome": "AutoLeilões SP",
        "site_title": "Leilões Judiciais e Extrajudiciais de Carros e Motos",
        "site_description": "Editais de leilão judicial e extrajudicial de veículos",
        "site_keywords": "leilão, judicial, edital",
        "site_body_excerpt": "Veículos seminovos em leilão judicial. Edital disponível.",
        "dominio": "https://example.com",
    }
    out = classify(row)
    # nenhum strong (imovel/casa/etc.) em lugar nenhum → não pode ser high
    assert out["confidence"] == "medium"


def test_judicial_real_estate_site_high():
    """Caso real do INNLEI: 'Leilões Judiciais e Extrajudiciais' + 'imóveis' no body → high."""
    row = {
        "nome": "Daniel Elias Garcia",
        "site_title": "Daniel Garcia Leilões - Leiloeiro Oficial | Leilões Judiciais e Extrajudiciais",
        "site_description": "Leilões Judiciais e Extrajudiciais, Online e Presenciais",
        "site_keywords": "",
        "site_body_excerpt": "Imóveis, apartamentos e casas em leilão judicial. Edital com matrícula.",
        "dominio": "https://example.com",
    }
    out = classify(row)
    assert out["confidence"] == "high"


def test_no_signal_unknown():
    row = {
        "nome": "Fulano de Tal",
        "site_title": "",
        "site_description": "",
        "site_keywords": "",
        "site_body_excerpt": "",
        "dominio": "",
    }
    out = classify(row)
    assert out["confidence"] == "unknown"
    assert out["real_estate_score"] == 0


def test_score_caps_repetition_per_source():
    # body com strong keyword 100 vezes não deve dominar o score
    row = {
        "nome": "X",
        "site_title": "",
        "site_description": "",
        "site_keywords": "",
        "site_body_excerpt": "imovel " * 100,
        "dominio": "x",
    }
    score, _ = score_row(row)
    # cap por fonte = 3 hits * W_BODY_STRONG (1.0) = 3, não 100
    assert score <= 3.5


def test_signals_recorded():
    row = {
        "nome": "Imobiliária X",
        "site_title": "Apartamento em leilão",
        "site_description": "",
        "site_keywords": "",
        "site_body_excerpt": "",
        "dominio": "x",
    }
    out = classify(row)
    sigs = out["match_signals"].split("|")
    assert any(s.startswith("name+") for s in sigs)
    assert any(s.startswith("title+") for s in sigs)
