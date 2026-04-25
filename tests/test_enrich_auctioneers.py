from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from discovery import enrich_auctioneers as mod


HTML_HOUSE = """
<html><head>
  <title>Frazão Imóveis - Leilão de imóveis e apartamentos</title>
  <meta name="description" content="Leilão judicial e extrajudicial de imóveis em SP.">
  <meta name="keywords" content="imóveis, leilão, apartamento">
</head><body>
  <h1>Bem-vindo</h1>
  <script>var x = 1;</script>
  <p>Encontre apartamentos, casas e terrenos em leilão.</p>
</body></html>
"""

HTML_VEHICLES = """
<html><head>
  <title>AutoLeilões - Veículos</title>
  <meta property="og:description" content="Leilão de carros e motos."/>
</head><body>Carros, motos e caminhões.</body></html>
"""


def test_extract_meta_house():
    meta = mod.extract_meta(HTML_HOUSE)
    assert "Imóveis" in meta["site_title"]
    assert "imóveis" in meta["site_description"].lower()
    assert "leilão" in meta["site_keywords"].lower()
    assert "apartamentos" in meta["site_body_excerpt"].lower()
    # script removido
    assert "var x" not in meta["site_body_excerpt"]


def test_extract_meta_picks_og_description():
    meta = mod.extract_meta(HTML_VEHICLES)
    assert meta["site_description"].lower().startswith("leilão de carros")


@pytest.mark.asyncio
async def test_fetch_one_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", tmp_path)

    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text=HTML_HOUSE, headers={"content-type": "text/html"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        first = await mod.fetch_one(client, "https://example.com/")
        second = await mod.fetch_one(client, "https://example.com/")

    assert first["site_status_code"] == 200
    assert "Imóveis" in first["site_title"]
    assert second["_cache_hit"] is True
    assert calls["n"] == 1  # segunda chamada não bateu na rede


@pytest.mark.asyncio
async def test_fetch_one_handles_500(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", tmp_path)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await mod.fetch_one(client, "https://broken.example/")
    assert result["site_error"] == "http_503"
    assert result["site_status_code"] == 503


@pytest.mark.asyncio
async def test_enrich_dataframe_marks_no_domain(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", tmp_path)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=HTML_HOUSE, headers={"content-type": "text/html"})

    rows = [
        {"id": "1", "nome": "A", "dominio": "https://a.example/"},
        {"id": "2", "nome": "B", "dominio": ""},
    ]

    # Patch httpx.AsyncClient to use MockTransport
    real_async = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    enriched = await mod.enrich_dataframe(rows, concurrency=2, timeout=5.0, use_cache=False)

    assert len(enriched) == 2
    assert enriched[0]["site_status_code"] == 200
    assert enriched[1]["site_error"] == "no_domain"
    assert enriched[1]["site_status_code"] == ""
