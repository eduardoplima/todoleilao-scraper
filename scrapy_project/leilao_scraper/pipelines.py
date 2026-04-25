"""Pipelines do `leilao_scraper`.

Encadeamento (menor prioridade roda primeiro):

  100  ValidationPipeline       — descarta sem url ou sem auctioneer
  200  DeduplicationPipeline    — descarta url repetida no mesmo run
  300  EnrichmentPipeline       — calcula discount_pct
  900  JsonLinesExportPipeline  — grava data/raw/{name}/{ts}.jsonl

Nota sobre redundância com `FEEDS`: o `FEEDS` configurado em settings.py
também escreve JSONL no mesmo diretório. Os dois coexistem por escolha:
`FEEDS` é o caminho rápido do CLI Scrapy (`scrapy crawl X` já gera o
arquivo), e a pipeline garante o mesmo output mesmo quando outros
mecanismos rodam (ex.: orquestração via Python, `scrapy crawl X -o -`).
Em cenários onde 2x o disco é problema, comente um dos dois.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ValidationPipeline:
    """Descarta itens que não têm url ou auctioneer (campos não-negociáveis)."""

    def __init__(self) -> None:
        self.dropped_missing_url = 0
        self.dropped_missing_auctioneer = 0

    def process_item(self, item: Any, spider: Any) -> Any:
        adapter = ItemAdapter(item)
        url = (adapter.get("url") or "").strip() if isinstance(adapter.get("url"), str) else adapter.get("url")
        auctioneer = (
            (adapter.get("auctioneer") or "").strip()
            if isinstance(adapter.get("auctioneer"), str)
            else adapter.get("auctioneer")
        )
        if not url:
            self.dropped_missing_url += 1
            raise DropItem("ValidationPipeline: missing url")
        if not auctioneer:
            self.dropped_missing_auctioneer += 1
            raise DropItem("ValidationPipeline: missing auctioneer")
        return item

    def close_spider(self, spider: Any) -> None:
        total = self.dropped_missing_url + self.dropped_missing_auctioneer
        if total:
            logger.info(
                "ValidationPipeline: dropped %d (no_url=%d, no_auctioneer=%d)",
                total, self.dropped_missing_url, self.dropped_missing_auctioneer,
            )


# ---------------------------------------------------------------------------
# Deduplication (in-memory por run)
# ---------------------------------------------------------------------------

class DeduplicationPipeline:
    """Descarta itens com `url` já vista neste run.

    Usa `set` em memória. Para dedup cross-run, use uma pipeline de
    consolidação a jusante ou troque este `set` por SQLite.
    """

    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.duplicates = 0

    def process_item(self, item: Any, spider: Any) -> Any:
        adapter = ItemAdapter(item)
        url = adapter.get("url")
        if not isinstance(url, str):
            return item  # ValidationPipeline já deveria ter dropado
        if url in self.seen:
            self.duplicates += 1
            raise DropItem(f"DeduplicationPipeline: duplicate url {url}")
        self.seen.add(url)
        return item

    def close_spider(self, spider: Any) -> None:
        if self.duplicates:
            logger.info(
                "DeduplicationPipeline: %d duplicates dropped (%d unique)",
                self.duplicates, len(self.seen),
            )


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

class EnrichmentPipeline:
    """Calcula `discount_pct = (1 - minimum_bid / market_value) * 100`.

    Quando `minimum_bid` ou `market_value` estão ausentes, ou
    `market_value <= 0`, deixa o campo intocado. Tolerante a tipos: aceita
    Decimal, float, int ou string parsable.
    """

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    def process_item(self, item: Any, spider: Any) -> Any:
        adapter = ItemAdapter(item)
        mb = self._to_decimal(adapter.get("minimum_bid"))
        mv = self._to_decimal(adapter.get("market_value"))
        if mb is None or mv is None:
            return item
        if mv <= 0:
            logger.debug("EnrichmentPipeline: market_value<=0 (%s) — skip", mv)
            return item
        discount = (Decimal(1) - mb / mv) * Decimal(100)
        adapter["discount_pct"] = float(discount.quantize(Decimal("0.01")))
        return item


# ---------------------------------------------------------------------------
# JSON Lines export
# ---------------------------------------------------------------------------

class _ItemJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class JsonLinesExportPipeline:
    """Grava todos os itens em `data/raw/{spider}/{ts}.jsonl`.

    `ts` é o instante de abertura do arquivo em UTC (ISO 8601 com `Z` e
    `:` substituído por `-` para ser válido em filesystem).
    """

    def __init__(self, project_root: Path | None = None) -> None:
        if project_root is None:
            # default: três níveis acima deste arquivo
            project_root = Path(__file__).resolve().parent.parent.parent
        self.project_root = project_root
        self.file = None
        self.path: Path | None = None
        self.count = 0

    @classmethod
    def from_crawler(cls, crawler):
        # respeita PROJECT_ROOT do settings se disponível
        project_root: Path | None = None
        try:
            from .settings import PROJECT_ROOT  # type: ignore
            project_root = Path(PROJECT_ROOT)
        except Exception:
            project_root = None
        return cls(project_root=project_root)

    def open_spider(self, spider: Any) -> None:
        spider_dir = self.project_root / "data" / "raw" / spider.name
        spider_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        self.path = spider_dir / f"{ts}.jsonl"
        self.file = self.path.open("w", encoding="utf-8")
        spider.logger.info("JsonLinesExportPipeline → %s", self.path)

    def close_spider(self, spider: Any) -> None:
        if self.file is not None:
            self.file.close()
            spider.logger.info(
                "JsonLinesExportPipeline: %d itens gravados em %s",
                self.count, self.path,
            )

    def process_item(self, item: Any, spider: Any) -> Any:
        if self.file is None:
            return item
        adapter = ItemAdapter(item)
        self.file.write(
            json.dumps(adapter.asdict(), cls=_ItemJSONEncoder, ensure_ascii=False)
            + "\n"
        )
        self.count += 1
        return item
