"""Testes das pipelines."""
from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from scrapy.exceptions import DropItem

from leilao_scraper.items import PropertyItem
from leilao_scraper.pipelines import (
    DeduplicationPipeline,
    EnrichmentPipeline,
    JsonLinesExportPipeline,
    ValidationPipeline,
)


# ---- helpers --------------------------------------------------------------

class _Logger:
    def __init__(self): self.logs: list[str] = []
    def info(self, msg, *a, **kw): self.logs.append(("info", msg, a))
    def debug(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass


def _make_spider(name: str = "test_spider"):
    return SimpleNamespace(name=name, logger=_Logger())


def _item(**kwargs) -> PropertyItem:
    return PropertyItem(**kwargs)


# ---- ValidationPipeline ----------------------------------------------------

def test_validation_passes_complete_item():
    p = ValidationPipeline()
    item = _item(url="https://x.com/1", auctioneer="frazao")
    assert p.process_item(item, _make_spider()) is item


def test_validation_drops_missing_url():
    p = ValidationPipeline()
    item = _item(auctioneer="frazao")
    with pytest.raises(DropItem, match="missing url"):
        p.process_item(item, _make_spider())
    assert p.dropped_missing_url == 1


def test_validation_drops_empty_url():
    p = ValidationPipeline()
    item = _item(url="   ", auctioneer="frazao")
    with pytest.raises(DropItem, match="missing url"):
        p.process_item(item, _make_spider())


def test_validation_drops_missing_auctioneer():
    p = ValidationPipeline()
    item = _item(url="https://x.com/1")
    with pytest.raises(DropItem, match="missing auctioneer"):
        p.process_item(item, _make_spider())
    assert p.dropped_missing_auctioneer == 1


# ---- DeduplicationPipeline -------------------------------------------------

def test_dedup_lets_through_unique():
    p = DeduplicationPipeline()
    spider = _make_spider()
    item1 = _item(url="https://x.com/1", auctioneer="a")
    item2 = _item(url="https://x.com/2", auctioneer="a")
    assert p.process_item(item1, spider) is item1
    assert p.process_item(item2, spider) is item2
    assert p.duplicates == 0
    assert len(p.seen) == 2


def test_dedup_drops_duplicate_url():
    p = DeduplicationPipeline()
    spider = _make_spider()
    item1 = _item(url="https://x.com/1", auctioneer="a")
    item2 = _item(url="https://x.com/1", auctioneer="b")  # mesma url, leiloeiro diferente
    p.process_item(item1, spider)
    with pytest.raises(DropItem, match="duplicate url"):
        p.process_item(item2, spider)
    assert p.duplicates == 1


# ---- EnrichmentPipeline ----------------------------------------------------

def test_enrichment_computes_discount():
    p = EnrichmentPipeline()
    item = _item(
        url="https://x.com/1", auctioneer="a",
        minimum_bid=Decimal("250000.00"),
        market_value=Decimal("500000.00"),
    )
    p.process_item(item, _make_spider())
    assert item["discount_pct"] == 50.00


def test_enrichment_no_discount_when_equal():
    p = EnrichmentPipeline()
    item = _item(
        url="https://x.com/1", auctioneer="a",
        minimum_bid=Decimal("100"),
        market_value=Decimal("100"),
    )
    p.process_item(item, _make_spider())
    assert item["discount_pct"] == 0.00


def test_enrichment_negative_when_above_market():
    p = EnrichmentPipeline()
    item = _item(
        url="https://x.com/1", auctioneer="a",
        minimum_bid=Decimal("120"),
        market_value=Decimal("100"),
    )
    p.process_item(item, _make_spider())
    assert item["discount_pct"] == -20.00


def test_enrichment_skips_when_missing_market_value():
    p = EnrichmentPipeline()
    item = _item(url="https://x.com/1", auctioneer="a", minimum_bid=Decimal("100"))
    p.process_item(item, _make_spider())
    assert "discount_pct" not in item or item.get("discount_pct") in (None, "")


def test_enrichment_skips_when_market_value_zero():
    p = EnrichmentPipeline()
    item = _item(
        url="https://x.com/1", auctioneer="a",
        minimum_bid=Decimal("100"),
        market_value=Decimal("0"),
    )
    p.process_item(item, _make_spider())
    assert "discount_pct" not in item or item.get("discount_pct") in (None, "")


def test_enrichment_accepts_str_input():
    p = EnrichmentPipeline()
    item = _item(
        url="https://x.com/1", auctioneer="a",
        minimum_bid="250000",
        market_value="1000000",
    )
    p.process_item(item, _make_spider())
    assert item["discount_pct"] == 75.00


# ---- JsonLinesExportPipeline ----------------------------------------------

def test_export_writes_jsonl(tmp_path):
    p = JsonLinesExportPipeline(project_root=tmp_path)
    spider = _make_spider("frazao_leiloes")
    p.open_spider(spider)
    p.process_item(_item(
        url="https://x.com/1", auctioneer="frazao",
        title="Apto", minimum_bid=Decimal("250000.00"),
    ), spider)
    p.process_item(_item(
        url="https://x.com/2", auctioneer="frazao",
        title="Casa",
    ), spider)
    p.close_spider(spider)

    output_dir = tmp_path / "data" / "raw" / "frazao_leiloes"
    files = list(output_dir.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["url"] == "https://x.com/1"
    assert first["title"] == "Apto"
    # Decimal foi serializado como string
    assert first["minimum_bid"] == "250000.00"


def test_export_one_file_per_run(tmp_path):
    p = JsonLinesExportPipeline(project_root=tmp_path)
    spider = _make_spider("alpha")
    p.open_spider(spider)
    p.close_spider(spider)
    files = list((tmp_path / "data" / "raw" / "alpha").glob("*.jsonl"))
    assert len(files) == 1
    # filename é ISO 8601 (sem `:`) com sufixo Z
    assert files[0].name.endswith("Z.jsonl")
