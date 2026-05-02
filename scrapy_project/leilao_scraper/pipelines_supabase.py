"""SupabasePipeline — persiste PropertyItem no schema `core.*`.

Ativada apenas quando `SUPABASE_DB_URL` está definida no ambiente. Sem
ela, a pipeline fica inerte (graceful degrade para dev sem Supabase).

Mapeamento mínimo viável (Fase 1):
    PropertyItem.url, host          → core.source (UPSERT por short_name)
    PropertyItem.scraped_at, url    → core.scrape_event (INSERT)
    PropertyItem.address (dict)     → core.address (INSERT, geom NULL)
    address + áreas + property_type → core.spatial_unit (INSERT)
    auctioneer slug                 → core.auctioneer (UPSERT por full_name)
    PropertyItem (URL+code)         → core.auction (UPSERT por source_auction_code)
                                       + core.auction_lot (UPSERT por
                                         (source_id, source_lot_code))
    minimum_bid + auction dates     → core.auction_round (1-2 rounds)
    PropertyItem.bids[]             → core.bid (INSERT)
    images[], documents[]           → core.image, core.document
    status='arrematado' + último    → UPDATE auction_lot.final_price/final_at

Idempotente: re-rodar não duplica linhas (UPSERT em chaves naturais).
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

from itemadapter import ItemAdapter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers de coerção
# ---------------------------------------------------------------------------


def _to_decimal(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _to_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _parse_dt(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _host(url: str) -> str:
    return (urlparse(url or "").hostname or "").lower()


_LOT_STATUS_MAP = {
    # PropertyItem.status → core.lot_status enum
    "aberto": "ativo",
    "arrematado": "arrematado",
    "cancelado": "fracassado",
    "desconhecido": "futuro",
}


def _map_lot_status(status: str | None) -> str:
    if not status:
        return "futuro"
    return _LOT_STATUS_MAP.get(status, "futuro")


# Mapeia property_type (PropertyItem) → unit_kind enum (core.spatial_unit.kind)
_UNIT_KIND_MAP = {
    "apartamento": "apartamento",
    "casa": "casa",
    "terreno": "terreno_urbano",
    "comercial": "sala_comercial",
    "rural": "fazenda",
    "outro": "desconhecida",
}


def _map_unit_kind(t: str | None) -> str:
    if not t:
        return "desconhecida"
    return _UNIT_KIND_MAP.get(t, "desconhecida")


# Heurística leve: edital / matrícula / laudo / outro a partir do label
def _classify_document(label: str) -> str:
    s = (label or "").lower()
    if "edital" in s:
        return "edital"
    if "matr" in s:  # matrícula / matricula
        return "matricula"
    if "laudo" in s:
        return "laudo"
    if "certid" in s:
        return "certidao"
    return "outro"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


PARSER_VERSION = "spider-supabase-v1"


class SupabasePipeline:
    """Persiste itens no Postgres Supabase via psycopg v3.

    Conexão única por spider run (low concurrency). Cada item entra em
    uma transação separada — falha de um item não corrompe o batch.
    """

    @classmethod
    def from_crawler(cls, crawler):
        dsn = os.environ.get("SUPABASE_DB_URL")
        if not dsn:
            crawler.spider.logger.info(
                "SupabasePipeline: SUPABASE_DB_URL ausente — pipeline inerte"
            )
            return cls(dsn=None)
        return cls(dsn=dsn)

    def __init__(self, dsn: str | None) -> None:
        self.dsn = dsn
        self.conn = None
        self.persisted = 0
        self.failed = 0

    def open_spider(self, spider: Any) -> None:
        if not self.dsn:
            return
        # Lazy import — evita exigir psycopg em dev local sem Supabase
        import psycopg

        self.conn = psycopg.connect(self.dsn, autocommit=False)
        spider.logger.info(
            "SupabasePipeline: conectado em %s", _host(self.dsn) or "<dsn>"
        )

    def close_spider(self, spider: Any) -> None:
        if self.conn is not None:
            self.conn.close()
            spider.logger.info(
                "SupabasePipeline: %d items persistidos, %d falhas",
                self.persisted,
                self.failed,
            )

    @contextmanager
    def _txn(self):
        assert self.conn is not None
        try:
            yield self.conn.cursor()
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def process_item(self, item: Any, spider: Any) -> Any:
        if self.conn is None:
            return item
        try:
            with self._txn() as cur:
                self._persist(cur, item, spider)
            self.persisted += 1
        except Exception as exc:  # noqa: BLE001 — pipeline não pode quebrar batch
            self.failed += 1
            spider.logger.warning(
                "SupabasePipeline: falha em %s: %s",
                ItemAdapter(item).get("url"),
                exc,
                exc_info=False,
            )
        return item

    # ------------------------------------------------------------------
    # Núcleo de persistência
    # ------------------------------------------------------------------

    def _persist(self, cur, item: Any, spider: Any) -> None:
        a = ItemAdapter(item)
        url = a.get("url")
        if not url:
            return

        host = _host(url)
        source_id = self._upsert_source(cur, host, url)
        self._insert_scrape_event(cur, source_id, url, a.get("scraped_at"))

        auctioneer_id = self._upsert_auctioneer(cur, a.get("auctioneer") or "desconhecido")

        address_id = self._insert_address(cur, a.get("address") or {})
        unit_id = self._insert_spatial_unit(cur, a, address_id, source_id)

        auction_id = self._upsert_auction(cur, source_id, auctioneer_id, url)
        lot_id, was_new_lot = self._upsert_auction_lot(cur, source_id, auction_id, a, url)

        # Link N:N lot↔unit (com share_pct=NULL → 100% único)
        if unit_id is not None:
            cur.execute(
                """
                INSERT INTO core.lot_unit_link (lot_id, spatial_unit_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (lot_id, unit_id),
            )

        round_id = self._insert_round(cur, lot_id, a)
        bid_ids = self._insert_bids(cur, lot_id, round_id, source_id, a)

        # Resultado final: se status=arrematado e há bids, último bid é o vencedor
        if a.get("status") == "arrematado" and bid_ids:
            last_bid = bid_ids[-1]
            final_amount = _to_decimal((a.get("bids") or [{}])[-1].get("value_brl"))
            cur.execute(
                """
                UPDATE core.auction_lot
                   SET winning_bid_id = %s,
                       final_price    = COALESCE(%s, final_price),
                       final_at       = COALESCE(%s, final_at),
                       current_status = 'arrematado'
                 WHERE id = %s
                """,
                (last_bid, final_amount, _parse_dt(a.get("second_auction_date")), lot_id),
            )

        for img in (a.get("images") or [])[:50]:
            cur.execute(
                """
                INSERT INTO core.image (lot_id, source_url, source_id, scraped_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT DO NOTHING
                """,
                (lot_id, img if isinstance(img, str) else img.get("url"), source_id),
            )

        for doc in (a.get("documents") or [])[:20]:
            doc_url = doc.get("url") if isinstance(doc, dict) else None
            if not doc_url:
                continue
            label = doc.get("name") if isinstance(doc, dict) else None
            cur.execute(
                """
                INSERT INTO core.document
                    (kind, lot_id, source_url, title, source_id, parser_version, scraped_at)
                VALUES (%s, %s, %s, %s, %s, %s, now())
                """,
                (
                    _classify_document(label or ""),
                    lot_id,
                    doc_url,
                    label,
                    source_id,
                    PARSER_VERSION,
                ),
            )

    # ------------------------------------------------------------------
    # UPSERTs / INSERTs específicos
    # ------------------------------------------------------------------

    def _upsert_source(self, cur, host: str, url: str) -> str:
        cur.execute(
            """
            INSERT INTO core.source (short_name, display_name, base_url, source_kind)
            VALUES (%s, %s, %s, 'auctioneer')
            ON CONFLICT (short_name) DO UPDATE
              SET base_url = EXCLUDED.base_url
            RETURNING id
            """,
            (host or "unknown", host or url, f"https://{host}/" if host else url),
        )
        return cur.fetchone()[0]

    def _insert_scrape_event(self, cur, source_id: str, url: str, scraped_at: Any) -> None:
        cur.execute(
            """
            INSERT INTO core.scrape_event
                (source_id, url, scraped_at, parser_version, parse_status)
            VALUES (%s, %s, COALESCE(%s, now()), %s, 'success')
            """,
            (source_id, url, _parse_dt(scraped_at), PARSER_VERSION),
        )

    def _upsert_auctioneer(self, cur, slug: str) -> str | None:
        if not slug:
            return None
        # Sem coluna `slug` no DDL; usamos full_name como chave e fingimos
        # que o slug é o nome canônico nesta v1.
        cur.execute(
            """
            INSERT INTO core.auctioneer (full_name)
            VALUES (%s)
            ON CONFLICT DO NOTHING
            """,
            (slug,),
        )
        cur.execute("SELECT id FROM core.auctioneer WHERE full_name = %s", (slug,))
        row = cur.fetchone()
        return row[0] if row else None

    def _insert_address(self, cur, addr: dict) -> str | None:
        if not addr:
            return None
        cur.execute(
            """
            INSERT INTO core.address
                (street_name, number, complement, district, uf, cep, raw_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                addr.get("street"),
                addr.get("number"),
                addr.get("complement"),
                addr.get("neighborhood"),
                addr.get("state"),
                _normalize_cep(addr.get("zip")),
                addr.get("raw_text") or _build_raw_text(addr),
            ),
        )
        return cur.fetchone()[0]

    def _insert_spatial_unit(self, cur, a: ItemAdapter, address_id: str | None, source_id: str) -> str | None:
        cur.execute(
            """
            INSERT INTO core.spatial_unit
                (kind, address_id, total_area, useful_area,
                 bedrooms, bathrooms, parking_spots,
                 appraisal_value, source_id, scraped_at, parser_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()), %s)
            RETURNING id
            """,
            (
                _map_unit_kind(a.get("property_type")),
                address_id,
                _to_decimal(a.get("total_area_sqm")),
                _to_decimal(a.get("area_sqm")),
                _to_int(a.get("bedrooms")),
                _to_int(a.get("bathrooms")),
                _to_int(a.get("parking_spots")),
                _to_decimal(a.get("market_value")),
                source_id,
                _parse_dt(a.get("scraped_at")),
                PARSER_VERSION,
            ),
        )
        return cur.fetchone()[0]

    def _upsert_auction(
        self, cur, source_id: str, auctioneer_id: str | None, source_url: str
    ) -> str:
        # 1 leilão por listagem (source_listing_url) — v1 grosseiro: 1 leilão
        # por scrape_event de URL de detalhe. Refinamento futuro: agrupar por
        # leilao_id extraído da URL /leilao/{id}/lotes.
        code = source_url
        cur.execute(
            """
            INSERT INTO core.auction
                (modality, origin, auctioneer_id,
                 source_id, source_auction_code, source_url,
                 scraped_at, parser_version)
            VALUES ('judicial_cpc', 'desconhecida', %s, %s, %s, %s, now(), %s)
            ON CONFLICT DO NOTHING
            """,
            (auctioneer_id, source_id, code, source_url, PARSER_VERSION),
        )
        cur.execute(
            "SELECT id FROM core.auction WHERE source_id = %s AND source_auction_code = %s",
            (source_id, code),
        )
        return cur.fetchone()[0]

    def _upsert_auction_lot(
        self, cur, source_id: str, auction_id: str, a: ItemAdapter, url: str
    ) -> tuple[str, bool]:
        lot_code = a.get("source_lot_code") or url
        status = _map_lot_status(a.get("status"))
        appraisal = _to_decimal(a.get("market_value"))

        cur.execute(
            """
            INSERT INTO core.auction_lot
                (auction_id, source_id, source_lot_code, source_url,
                 current_status, appraisal_value,
                 scraped_at, parser_version)
            VALUES (%s, %s, %s, %s, %s, %s, now(), %s)
            ON CONFLICT (source_id, source_lot_code) DO UPDATE
              SET current_status   = EXCLUDED.current_status,
                  appraisal_value  = COALESCE(EXCLUDED.appraisal_value, core.auction_lot.appraisal_value),
                  source_url       = EXCLUDED.source_url,
                  last_seen_at     = now(),
                  scraped_at       = EXCLUDED.scraped_at
            RETURNING id, (xmax = 0) AS inserted
            """,
            (
                auction_id, source_id, lot_code, url,
                status, appraisal, PARSER_VERSION,
            ),
        )
        row = cur.fetchone()
        return row[0], bool(row[1])

    def _insert_round(self, cur, lot_id: str, a: ItemAdapter) -> str | None:
        scheduled = _parse_dt(a.get("second_auction_date") or a.get("first_auction_date"))
        minimum_bid = _to_decimal(a.get("minimum_bid"))
        if scheduled is None or minimum_bid is None:
            return None
        # round_number 2 se SOLEON expõe só "Encerramento" (segunda praça
        # padrão). Heurística leve.
        round_number = 2 if a.get("auction_phase") == "2a_praca" else 1
        cur.execute(
            """
            INSERT INTO core.auction_round
                (lot_id, round_number, scheduled_at, minimum_bid, status,
                 scraped_at, parser_version)
            VALUES (%s, %s, %s, %s, 'futura', now(), %s)
            ON CONFLICT (lot_id, round_number) DO UPDATE
              SET scheduled_at = EXCLUDED.scheduled_at,
                  minimum_bid  = EXCLUDED.minimum_bid
            RETURNING id
            """,
            (lot_id, round_number, scheduled, minimum_bid, PARSER_VERSION),
        )
        return cur.fetchone()[0]

    def _insert_bids(
        self, cur, lot_id: str, round_id: str | None, source_id: str, a: ItemAdapter
    ) -> list[str]:
        bids = a.get("bids") or []
        if not bids or round_id is None:
            return []
        ids: list[str] = []
        for b in bids:
            ts = _parse_dt(b.get("timestamp"))
            amount = _to_decimal(b.get("value_brl"))
            if ts is None or amount is None:
                continue
            cur.execute(
                """
                INSERT INTO core.bid
                    (round_id, lot_id, amount, placed_at,
                     status, notes, source_id, scraped_at)
                VALUES (%s, %s, %s, %s, 'registrado', %s, %s, now())
                RETURNING id
                """,
                (round_id, lot_id, amount, ts, b.get("bidder_raw"), source_id),
            )
            ids.append(cur.fetchone()[0])
        return ids


# ---------------------------------------------------------------------------
# Helpers de address
# ---------------------------------------------------------------------------


def _normalize_cep(raw: Any) -> str | None:
    if not raw:
        return None
    s = "".join(c for c in str(raw) if c.isdigit())
    return s if len(s) == 8 else None


def _build_raw_text(addr: dict) -> str:
    parts = [
        addr.get("street"),
        addr.get("number"),
        addr.get("complement"),
        addr.get("neighborhood"),
        addr.get("city"),
        addr.get("state"),
        addr.get("zip"),
    ]
    return ", ".join(p for p in parts if p)
