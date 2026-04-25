from __future__ import annotations

from discovery.site_analyzer import (
    count_links,
    detect_tech,
    determine_rendering,
    extract_title_and_generator,
    requires_js_for_listings,
)

WP_HTML = """
<!doctype html>
<html><head>
  <title>Frazão Imóveis</title>
  <meta name="generator" content="WordPress 6.5">
  <link rel="stylesheet" href="https://example.com/wp-content/themes/x/style.css">
</head><body>
<a href="/imoveis/123">Apartamento 1</a>
<a href="/lote/456">Lote 2</a>
<a href="javascript:void(0)">noop</a>
<a href="mailto:x@y.com">contato</a>
<a href="#topo">topo</a>
<a href="/sobre">Sobre</a>
</body></html>
"""

NEXTJS_HTML = """
<!doctype html><html><head>
<title>Leilo App</title>
<script>self.__next_f.push([0])</script>
<script src="/_next/static/chunks/app.js"></script>
</head><body><div id="__next">Carregando...</div></body></html>
"""


def test_count_links_filters_noise():
    total, useful = count_links(WP_HTML)
    # /imoveis/123, /lote/456, /sobre = 3 totais (javascript/mailto/# excluídos)
    assert total == 3
    # /imoveis e /lote contêm keywords úteis
    assert useful == 2


def test_count_links_empty():
    assert count_links("") == (0, 0)


def test_determine_rendering_static():
    # ambos retornam o mesmo número de links úteis → static
    assert determine_rendering(10, 10) == "static"
    assert determine_rendering(20, 15) == "static"  # dynamic ≤ static


def test_determine_rendering_dynamic():
    # dynamic ≥ 1.5x e diff ≥ 3
    assert determine_rendering(2, 10) == "dynamic"
    assert determine_rendering(0, 12) == "dynamic"


def test_determine_rendering_hybrid():
    # leve incremento, mas não 1.5x
    assert determine_rendering(10, 12) == "hybrid"


def test_determine_rendering_unknown_when_zero():
    assert determine_rendering(0, 0) == "unknown"


def test_requires_js_when_no_static_listings():
    assert requires_js_for_listings(0, 5) is True
    assert requires_js_for_listings(1, 20) is True  # 1 < 20*0.3=6
    assert requires_js_for_listings(10, 12) is False
    assert requires_js_for_listings(5, 0) is False


def test_detect_tech_wordpress():
    techs, signals = detect_tech(WP_HTML, "", {}, "https://x.com")
    assert "WordPress" in techs
    assert any("generator" in s.lower() for s in signals)


def test_detect_tech_nextjs():
    techs, _ = detect_tech(NEXTJS_HTML, "", {}, "https://x.leilao.br")
    assert "Next.js" in techs
    assert "leilao.br platform" in techs


def test_detect_tech_dedup():
    # mesma sinalização (wp-content + meta generator WordPress) só inclui WP uma vez
    techs, _ = detect_tech(WP_HTML, WP_HTML, {}, "")
    assert techs.count("WordPress") == 1


def test_extract_title_and_generator():
    title, gen = extract_title_and_generator(WP_HTML)
    assert title == "Frazão Imóveis"
    assert gen.lower().startswith("wordpress")


def test_extract_title_handles_missing():
    assert extract_title_and_generator("") == ("", "")
    assert extract_title_and_generator("<html><body>no title</body></html>") == ("", "")
