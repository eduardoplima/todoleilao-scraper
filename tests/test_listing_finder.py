from __future__ import annotations

import httpx
import pytest

from discovery.listing_finder import (
    detect_items,
    filter_sitemap_urls,
    find_candidates,
    score_candidate,
    validate_candidate,
)


HOME_HTML = """
<html><body>
  <nav>
    <a href="/imoveis">Imóveis</a>
    <a href="/leiloes-em-andamento">Leilões em andamento</a>
    <a href="/sobre-nos">Quem somos</a>
    <a href="/contato">Contato</a>
    <a href="javascript:void(0)">JS</a>
    <a href="/lotes?categoria=imovel">Lotes</a>
  </nav>
</body></html>
"""

LISTING_HTML = """
<html><body>
  <div class="card">
    <a href="/imovel/100">Apto Centro</a>
    <span>R$ 250.000,00</span>
  </div>
  <div class="card">
    <a href="/imovel/101">Casa Bairro</a>
    <span>R$ 150.000,00</span>
  </div>
  <div class="card">
    <a href="/imovel/102">Lote 1</a>
    <span>R$ 80.000</span>
  </div>
  <div class="card">
    <a href="/imovel/103">Sala Comercial</a>
    <span>R$ 1.200.000,50</span>
  </div>
  <div class="card">
    <a href="/imovel/104">Galpão</a>
    <span>R$ 2.000.000</span>
  </div>
  <div class="card">
    <a href="/imovel/105">Cobertura</a>
    <span>R$ 800.000</span>
  </div>
</body></html>
"""


def test_score_candidate_text_strong():
    score, reasons = score_candidate("Imóveis", "/imoveis-disponiveis")
    # text+ AND path+ → 10 + 6 = 16
    assert score == 16
    assert any(r.startswith("text+") for r in reasons)
    assert any(r.startswith("path+") for r in reasons)


def test_score_candidate_text_medium_only():
    score, reasons = score_candidate("Lotes em destaque", "/destaques")
    # text~lotes → 5
    assert score == 5
    assert reasons == ["text~lotes"]


def test_score_candidate_path_query_match():
    score, reasons = score_candidate("Veja", "/lotes?categoria=imovel")
    # path~lotes (3) — só conta UM medium do path mesmo tendo dois patterns
    # mas categoria=imovel é mais forte? Não, ambos são medium.
    assert score == 3


def test_score_candidate_no_match():
    score, reasons = score_candidate("Sobre", "/sobre-nos")
    assert score == 0
    assert reasons == []


def test_find_candidates_orders_by_score():
    cands = find_candidates(HOME_HTML, "https://example.com")
    urls = [c[0] for c in cands]
    # /imoveis (text+ + path+ = 16) deve vir primeiro
    assert urls[0] == "https://example.com/imoveis"
    # /lotes?categoria=imovel (text~lotes + path~lotes = 8)
    # /leiloes-em-andamento (text~leiloes + path~leiloes = 8)
    assert "https://example.com/lotes?categoria=imovel" in urls
    assert "https://example.com/leiloes-em-andamento" in urls
    # /sobre-nos não entra
    assert all("sobre-nos" not in u for u in urls)
    # javascript: filtrado
    assert all("javascript:" not in u for u in urls)


def test_detect_items_counts_prices():
    n, sample = detect_items(LISTING_HTML, "https://example.com")
    assert n == 6  # seis preços
    assert sample.startswith("https://example.com/imovel/")


def test_detect_items_empty():
    assert detect_items("", "https://x.com") == (0, "")
    assert detect_items("<p>nada aqui</p>", "https://x.com") == (0, "")


def test_filter_sitemap_urls():
    urls = [
        "https://x.com/sobre",
        "https://x.com/imoveis",
        "https://x.com/imoveis/123",
        "https://x.com/leiloes/2026",
        "https://x.com/contato",
    ]
    cands = filter_sitemap_urls(urls)
    paths = [c[0] for c in cands]
    assert "https://x.com/imoveis" in paths
    assert "https://x.com/leiloes/2026" in paths
    assert "https://x.com/sobre" not in paths


@pytest.mark.asyncio
async def test_validate_candidate_counts_items():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=LISTING_HTML, headers={"content-type": "text/html"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        n, sample, err = await validate_candidate(client, "https://example.com/imoveis")
    assert err == ""
    assert n == 6
    assert sample.endswith("/imovel/100")


@pytest.mark.asyncio
async def test_validate_candidate_404():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        n, sample, err = await validate_candidate(client, "https://x.com/no")
    assert err == "http_404"
    assert n == 0
