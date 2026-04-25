"""Testes unitários do scraper de descoberta INNLEI.

Usamos httpx.MockTransport para simular a API paginada — sem rede.
"""
from __future__ import annotations

import csv

import httpx
import pytest

from discovery.innlei_scraper import (
    BASE_URL,
    LIST_ENDPOINT,
    RateLimiter,
    fetch_all_auctioneers,
    write_csv,
)


def _sample(record_id: int, *, slug: str, uf: str, cidade: str) -> dict:
    return {
        "id": record_id,
        "slug": slug,
        "nome": f"Leiloeiro {record_id}",
        "email": f"leiloeiro{record_id}@example.com",
        "telefone": "(11)99999-9999",
        "celular": "(11)99999-9999",
        "endereco": "Rua dos Bobos, 0",
        "cidade": cidade,
        "cep": "01001-000",
        "dominio": f"https://leiloeiro{record_id}.com.br",
        "dominio_url": f"l{record_id}.leilao.br",
        "dominio_status": "ativo",
        "dominio_online": True,
        "situacao": "Regular",
        "juntaComercial": f"JUNTA COMERCIAL DE {uf}",
        "matricula": f"{record_id}-X",
        "anoPosse": "01/01/2020",
        "imagem": "",
        "facebook": "",
        "instagram": "",
        "linkedin": "",
        "youtube": "",
        "twitter": "",
        "credenciamento": "credenciado",
        "isAssociado": True,
        "nivel": "prata",
        "matriculas": [
            {"matricula": f"{record_id}-X", "junta": {"uf": uf, "sigla": f"JUC{uf}", "nome": f"JUNTA {uf}"}},
            {"matricula": f"{record_id}-Y", "junta": {"uf": "RJ", "sigla": "JUCERJA", "nome": "JUNTA RJ"}},
        ],
        "dadosJunta": {},
    }


def _build_mock_handler():
    page1 = [
        _sample(1, slug="alpha", uf="SP", cidade="São Paulo"),
        _sample(2, slug="beta", uf="MG", cidade="Belo Horizonte"),
    ]
    page2 = [
        _sample(3, slug="gamma", uf="PR", cidade="Curitiba"),
    ]
    pages = {1: page1, 2: page2}
    total = sum(len(p) for p in pages.values())
    total_pages = len(pages)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == LIST_ENDPOINT
        page = int(request.url.params.get("page", 1))
        limit = int(request.url.params.get("limit", 20))
        calls.append((page, limit))
        data = pages.get(page, [])
        return httpx.Response(
            200,
            json={
                "data": data,
                "page": page,
                "limit": limit,
                "total": total,
                "totalPages": total_pages,
            },
        )

    return handler, calls, total


def test_fetch_all_auctioneers_paginates_and_normalizes():
    handler, calls, total = _build_mock_handler()
    transport = httpx.MockTransport(handler)
    client = httpx.Client(base_url=BASE_URL, transport=transport)
    limiter = RateLimiter(min_interval_s=0.0)  # sem espera no teste

    records = fetch_all_auctioneers(client=client, page_size=2, limiter=limiter)

    assert len(records) == total == 3
    assert [r["id"] for r in records] == [1, 2, 3]
    # paginou as duas páginas
    assert {p for p, _ in calls} == {1, 2}
    # UF veio de matriculas[0].junta.sigla, não de juntaComercial
    assert records[0]["uf"] == "SP"
    assert records[2]["uf"] == "PR"
    # extras concatenadas
    assert "RJ" in records[0]["matriculas_extras"]
    # url do perfil aponta para a API /api/public/leiloeiros/{id}
    assert records[0]["url_perfil_innlei"].endswith("/api/public/leiloeiros/1")


def test_retry_on_5xx(monkeypatch):
    """Servidor retorna 503 nas duas primeiras chamadas e 200 na terceira."""
    monkeypatch.setattr("discovery.innlei_scraper.BACKOFF_BASE_S", 1.0)
    monkeypatch.setattr("time.sleep", lambda _: None)  # acelera o teste

    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(
            200,
            json={
                "data": [_sample(42, slug="x", uf="SP", cidade="Sampa")],
                "page": 1,
                "limit": 100,
                "total": 1,
                "totalPages": 1,
            },
        )

    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    limiter = RateLimiter(min_interval_s=0.0)
    records = fetch_all_auctioneers(client=client, limiter=limiter)
    assert attempts["n"] == 3
    assert len(records) == 1
    assert records[0]["id"] == 42


def test_write_csv_round_trip(tmp_path):
    handler, _, _ = _build_mock_handler()
    transport = httpx.MockTransport(handler)
    client = httpx.Client(base_url=BASE_URL, transport=transport)
    records = fetch_all_auctioneers(
        client=client, page_size=2, limiter=RateLimiter(min_interval_s=0.0)
    )

    out = tmp_path / "raw.csv"
    n = write_csv(records, out)
    assert n == 3
    with out.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 3
    assert rows[0]["nome"] == "Leiloeiro 1"
    assert rows[0]["uf"] == "SP"


def test_max_retries_exceeded():
    """Erros 5xx persistentes devem propagar como HTTPStatusError."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    limiter = RateLimiter(min_interval_s=0.0)
    import time as time_mod
    original_sleep = time_mod.sleep
    time_mod.sleep = lambda _: None
    try:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_all_auctioneers(client=client, limiter=limiter)
    finally:
        time_mod.sleep = original_sleep
