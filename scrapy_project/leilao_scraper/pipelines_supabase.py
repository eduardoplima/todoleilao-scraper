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

import hashlib
import re
import unicodedata

logger = logging.getLogger(__name__)


# Providers cujos spiders raspam direto do portal do banco. Esses lots viram
# `secondary` no dedup canonical_link quando há match com lot de leiloeiro.
BANK_PROVIDERS = frozenset({"caixa", "banco_brasil", "bradesco", "santander"})

# Regex de matrícula imobiliária (CRI). Captura padrões comuns como
# "matrícula nº 123.456", "matricula 12345", "matr. 12.345 do CRI".
_REGISTRY_RE = re.compile(
    r"matr[ií]cula?[^0-9]{0,20}(?:n[ºo°.]?\s*)?(\d{1,3}(?:\.\d{3})*|\d{3,8})",
    re.I,
)


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
    """Hostname canônico (lowercase, sem 'www.').

    Mesmo leiloeiro pode ter href com `www.x` e sem (mistura comum em
    SOLEON). Sem normalização, geram 2 entradas em core.source pra
    mesma fonte. Strip `www.` resolve.
    """
    h = (urlparse(url or "").hostname or "").lower()
    if h.startswith("www."):
        h = h[4:]
    return h


_LOT_STATUS_MAP = {
    # PropertyItem.status → core.lot_status enum (DDL: futuro, aberto, suspenso,
    # arrematado, deserto, adjudicado, remido, cancelado, desconhecido).
    "aberto": "aberto",
    "suspenso": "suspenso",
    "arrematado": "arrematado",
    "deserto": "deserto",
    "adjudicado": "adjudicado",
    "remido": "remido",
    "cancelado": "cancelado",
    "futuro": "futuro",
    "desconhecido": "desconhecido",
}


def _map_lot_status(status: str | None) -> str:
    if not status:
        return "desconhecido"
    return _LOT_STATUS_MAP.get(status, "desconhecido")


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
    """Mapeia rótulo livre → enum core.document_kind.

    Enum: edital, edital_complementar, laudo_avaliacao, matricula,
    certidao_onus, certidao_iptu, certidao_condominio, auto_arrematacao,
    termo_direito_preferencia, ficha_lote, planta_imovel, outro.
    """
    s = (label or "").lower()
    if "complement" in s and "edital" in s:
        return "edital_complementar"
    if "edital" in s:
        return "edital"
    if "matr" in s:  # matrícula / matricula
        return "matricula"
    if "laudo" in s:
        return "laudo_avaliacao"
    if "certid" in s:
        if "iptu" in s:
            return "certidao_iptu"
        if "condom" in s:
            return "certidao_condominio"
        if "ônus" in s or "onus" in s:
            return "certidao_onus"
        return "outro"
    if "auto" in s and "arrematac" in s:
        return "auto_arrematacao"
    if "ficha" in s:
        return "ficha_lote"
    if "planta" in s:
        return "planta_imovel"
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
        provider_slug = getattr(spider, "provider_slug", "") or ""
        source_kind = "bank" if provider_slug in BANK_PROVIDERS else "auctioneer"
        source_id = self._upsert_source(cur, host, url, source_kind=source_kind)
        self._insert_scrape_event(cur, source_id, url, a.get("scraped_at"))

        auctioneer_id = self._upsert_auctioneer(
            cur,
            a.get("auctioneer") or "desconhecido",
            extra=a.get("auctioneer_data"),
        )

        address_id = self._insert_address(cur, a.get("address") or {})

        # Auction + lot UPSERT primeiro pra obter lot_id; spatial_unit é
        # resolvida via lookup pelo lot_unit_link existente (idempotente,
        # sem inflação herdada do bug pré-dedup_auction_spatial).
        auction_id = self._upsert_auction(cur, source_id, auctioneer_id, url)
        lot_id, was_new_lot = self._upsert_auction_lot(cur, source_id, auction_id, a, url)

        unit_id = self._upsert_spatial_unit_for_lot(
            cur, lot_id, a, address_id, source_id
        )
        # Classifica kind a partir da description (caminho A do plano B1).
        # Trigger AFTER UPDATE OF description em auction_lot só dispara
        # quando description muda; chamada explícita aqui garante que
        # spatial_units recém-criadas/UPSERTed também classifiquem.
        cur.execute("SELECT core.classify_lot_kinds(%s)", (lot_id,))

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

        # Cláusulas estruturadas (idempotentes via DELETE+INSERT por lot)
        self._replace_payment_options(cur, lot_id, a.get("payment_options") or [])
        if unit_id is not None:
            ba_unit_id = self._ensure_ba_unit(cur, unit_id, source_id)
            self._replace_encumbrances(cur, ba_unit_id, source_id, a.get("encumbrances") or [])

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

        # Dedup inter-fontes: liga lots da Caixa/BB/etc. ao lote oficial do
        # leiloeiro quando match por (address_key, registry_key). Idempotente.
        self._link_canonical(cur, lot_id, source_kind, a)

    # ------------------------------------------------------------------
    # UPSERTs / INSERTs específicos
    # ------------------------------------------------------------------

    def _upsert_source(self, cur, host: str, url: str, source_kind: str = "auctioneer") -> str:
        cur.execute(
            """
            INSERT INTO core.source (short_name, display_name, base_url, source_kind)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (short_name) DO UPDATE
              SET base_url    = EXCLUDED.base_url,
                  source_kind = EXCLUDED.source_kind
            RETURNING id
            """,
            (host or "unknown", host or url, f"https://{host}/" if host else url, source_kind),
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

    def _upsert_auctioneer(
        self, cur, full_name: str, extra: dict | None = None
    ) -> str | None:
        """UPSERT por full_name. Atualiza juc_uf+jucesp_number se vierem novos.

        full_name é a chave de idempotência (UNIQUE constraint). Extra é o
        dict opcional com {juc_uf, jucesp_number} extraído pelo spider.
        """
        if not full_name:
            return None
        juc_uf = (extra or {}).get("juc_uf")
        jucesp = (extra or {}).get("jucesp_number")
        cur.execute(
            """
            INSERT INTO core.auctioneer (full_name, juc_uf, jucesp_number)
            VALUES (%s, %s, %s)
            ON CONFLICT (full_name) DO UPDATE
              SET juc_uf        = COALESCE(EXCLUDED.juc_uf, core.auctioneer.juc_uf),
                  jucesp_number = COALESCE(EXCLUDED.jucesp_number, core.auctioneer.jucesp_number),
                  updated_at    = now()
            RETURNING id
            """,
            (full_name, juc_uf, jucesp),
        )
        return cur.fetchone()[0]

    def _insert_address(self, cur, addr: dict) -> str | None:
        if not addr:
            return None
        # Aceita keys variantes: state/uf, zip/cep, street/street_name,
        # municipality_code (IBGE 7-dígitos quando spider conhece).
        uf_raw = (addr.get("uf") or addr.get("state") or "").upper().strip()
        uf = uf_raw[:2] if uf_raw else None
        muni_code = addr.get("municipality_code") or addr.get("ibge_code")
        # Valida IBGE (7 dígitos numéricos)
        if muni_code is not None:
            muni_code = str(muni_code).strip()
            if not (muni_code.isdigit() and len(muni_code) == 7):
                muni_code = None
        # Fallback: resolve IBGE via lookup core.municipality(name, uf)
        # quando spider sabe nome+UF mas não tem o código.
        muni_name = addr.get("municipality_name")
        if not muni_code and muni_name and uf:
            try:
                cur.execute(
                    """
                    SELECT ibge_code FROM core.municipality
                    WHERE uf = %s::core.uf_code
                      AND core.unaccent_lite(name) = core.unaccent_lite(%s)
                    LIMIT 1
                    """,
                    (uf, muni_name),
                )
                row = cur.fetchone()
                if row:
                    muni_code = row[0]
            except Exception:
                pass
        cur.execute(
            """
            INSERT INTO core.address
                (street_name, number, complement, district, uf, cep,
                 municipality_code, raw_text,
                 geom, geocoding_source, geocoding_confidence)
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                (SELECT centroid FROM core.municipality WHERE ibge_code = %s::text),
                CASE WHEN %s::text IS NOT NULL THEN 'municipality_centroid' ELSE NULL END,
                CASE WHEN %s::text IS NOT NULL THEN 0.1 ELSE NULL END
            )
            RETURNING id
            """,
            (
                addr.get("street_name") or addr.get("street"),
                addr.get("number"),
                addr.get("complement"),
                addr.get("neighborhood") or addr.get("district"),
                uf,
                _normalize_cep(addr.get("cep") or addr.get("zip")),
                muni_code,
                addr.get("raw_text") or _build_raw_text(addr),
                muni_code, muni_code, muni_code,
            ),
        )
        return cur.fetchone()[0]

    def _upsert_spatial_unit_for_lot(
        self, cur, lot_id: str, a: ItemAdapter, address_id: str | None, source_id: str
    ) -> str | None:
        """1 spatial_unit por lot (idempotente).

        Lookup primeiro: se já há spatial_unit linkada via lot_unit_link,
        UPDATE preservando campos não-nulos. Se não, INSERT + LINK.

        Resolve a inflação histórica em que cada UPSERT do lot criava
        nova spatial_unit. core.spatial_unit não tem chave natural
        confiável (registry_number raramente vem), então a chave de
        idempotência é o relacionamento via lot_unit_link.
        """
        kind         = _map_unit_kind(a.get("property_type"))
        total_area   = _to_decimal(a.get("total_area_sqm"))
        useful_area  = _to_decimal(a.get("area_sqm"))
        bedrooms     = _to_int(a.get("bedrooms"))
        bathrooms    = _to_int(a.get("bathrooms"))
        parking      = _to_int(a.get("parking_spots"))
        appraisal    = _to_decimal(a.get("market_value"))
        scraped      = _parse_dt(a.get("scraped_at"))

        cur.execute(
            """
            SELECT su.id FROM core.lot_unit_link lu
            JOIN core.spatial_unit su ON su.id = lu.spatial_unit_id
            WHERE lu.lot_id = %s
            ORDER BY su.created_at LIMIT 1
            """,
            (lot_id,),
        )
        row = cur.fetchone()
        if row is not None:
            unit_id = row[0]
            cur.execute(
                """
                UPDATE core.spatial_unit SET
                  kind            = CASE WHEN core.spatial_unit.kind = 'desconhecida'
                                         THEN %s ELSE core.spatial_unit.kind END,
                  address_id      = COALESCE(%s, address_id),
                  total_area      = COALESCE(%s, total_area),
                  useful_area     = COALESCE(%s, useful_area),
                  bedrooms        = COALESCE(%s, bedrooms),
                  bathrooms       = COALESCE(%s, bathrooms),
                  parking_spots   = COALESCE(%s, parking_spots),
                  appraisal_value = COALESCE(%s, appraisal_value),
                  scraped_at      = COALESCE(%s, scraped_at),
                  parser_version  = %s,
                  updated_at      = now()
                WHERE id = %s
                """,
                (
                    kind,
                    address_id,
                    total_area, useful_area,
                    bedrooms, bathrooms, parking,
                    appraisal, scraped, PARSER_VERSION,
                    unit_id,
                ),
            )
            return unit_id

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
                kind, address_id,
                total_area, useful_area,
                bedrooms, bathrooms, parking,
                appraisal, source_id, scraped, PARSER_VERSION,
            ),
        )
        unit_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO core.lot_unit_link (lot_id, spatial_unit_id) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            (lot_id, unit_id),
        )
        return unit_id

    def _upsert_auction(
        self, cur, source_id: str, auctioneer_id: str | None, source_url: str
    ) -> str:
        # 1 leilão por listagem (source_listing_url) — v1 grosseiro: 1 leilão
        # por scrape_event de URL de detalhe. Refinamento futuro: agrupar por
        # leilao_id extraído da URL /leilao/{id}/lotes.
        # Idempotente via UNIQUE (source_id, source_auction_code). Antes da
        # constraint o ON CONFLICT DO NOTHING não disparava (não havia
        # constraint), causando inflação 1.6× — corrigido em
        # sql/dedup_auction_spatial.sql.
        code = source_url
        cur.execute(
            """
            INSERT INTO core.auction
                (modality, origin, auctioneer_id,
                 source_id, source_auction_code, source_url,
                 scraped_at, last_seen_at, parser_version)
            VALUES ('judicial_cpc', 'desconhecida', %s, %s, %s, %s, now(), now(), %s)
            ON CONFLICT (source_id, source_auction_code) DO UPDATE
              SET source_url     = EXCLUDED.source_url,
                  auctioneer_id  = COALESCE(EXCLUDED.auctioneer_id, core.auction.auctioneer_id),
                  scraped_at     = EXCLUDED.scraped_at,
                  last_seen_at   = now()
            RETURNING id
            """,
            (auctioneer_id, source_id, code, source_url, PARSER_VERSION),
        )
        return cur.fetchone()[0]

    def _upsert_auction_lot(
        self, cur, source_id: str, auction_id: str, a: ItemAdapter, url: str
    ) -> tuple[str, bool]:
        lot_code = a.get("source_lot_code") or url
        lot_number = a.get("lot_number")
        description = a.get("description")
        status = _map_lot_status(a.get("status"))
        appraisal = _to_decimal(a.get("market_value"))
        # Persiste minimum_bid direto em auction_lot. Útil pra "venda direta"
        # (sem data de encerramento → sem auction_round). Em leilão judicial,
        # auction_round.minimum_bid permanece como verdade primária; view
        # public_v1.lot_search faz COALESCE pra escolher.
        min_bid = _to_decimal(a.get("minimum_bid"))

        # sale_mode: leilao (default) | venda_direta | leilao_e_venda_direta
        # Spider só envia non-null quando detecta texto "Venda direta até ...".
        sale_mode = (a.get("sale_mode") or "").strip().lower() or None
        direct_sale_deadline_at = _parse_dt(a.get("direct_sale_deadline"))

        cur.execute(
            """
            INSERT INTO core.auction_lot
                (auction_id, source_id, source_lot_code, source_url,
                 lot_number, current_status, appraisal_value, minimum_bid,
                 description, scraped_at, parser_version,
                 sale_mode, direct_sale_deadline_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s,
                    COALESCE(%s::core.sale_mode, 'leilao'),
                    %s)
            ON CONFLICT (source_id, source_lot_code) DO UPDATE
              SET current_status   = EXCLUDED.current_status,
                  appraisal_value  = COALESCE(EXCLUDED.appraisal_value, core.auction_lot.appraisal_value),
                  minimum_bid      = COALESCE(EXCLUDED.minimum_bid, core.auction_lot.minimum_bid),
                  lot_number       = COALESCE(EXCLUDED.lot_number, core.auction_lot.lot_number),
                  description      = COALESCE(EXCLUDED.description, core.auction_lot.description),
                  source_url       = EXCLUDED.source_url,
                  sale_mode        = CASE
                                       WHEN EXCLUDED.sale_mode <> 'leilao'
                                         THEN EXCLUDED.sale_mode
                                       ELSE core.auction_lot.sale_mode
                                     END,
                  direct_sale_deadline_at = COALESCE(
                      EXCLUDED.direct_sale_deadline_at,
                      core.auction_lot.direct_sale_deadline_at
                  ),
                  last_seen_at     = now(),
                  scraped_at       = EXCLUDED.scraped_at
            RETURNING id, (xmax = 0) AS inserted
            """,
            (
                auction_id, source_id, lot_code, url,
                lot_number, status, appraisal, min_bid, description, PARSER_VERSION,
                sale_mode, direct_sale_deadline_at,
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
        """Idempotente: substitui o histórico de bids do lote a cada UPSERT.

        Sem chave única natural (`bidder_party_id` está NULL na maioria),
        DELETE+INSERT é o caminho mais simples para evitar inflação. O
        histórico vem do site SOLEON (`div.ult_body div.ultimos-lances-item`)
        e é completo a cada fetch.
        """
        bids = a.get("bids") or []
        if round_id is None:
            return []
        # Zera FK winning_bid_id antes do DELETE para evitar
        # auction_lot_winning_bid_fk. O bloco subsequente em `_persist`
        # repopula winning_bid_id se status='arrematado'.
        cur.execute(
            "UPDATE core.auction_lot SET winning_bid_id = NULL WHERE id = %s",
            (lot_id,),
        )
        # Limpa bids prévios deste lot+source (idempotência por execução)
        cur.execute(
            "DELETE FROM core.bid WHERE lot_id = %s AND source_id = %s",
            (lot_id, source_id),
        )
        if not bids:
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

    # ------------------------------------------------------------------
    # ba_unit / payment_option / encumbrance
    # ------------------------------------------------------------------

    def _ensure_ba_unit(self, cur, spatial_unit_id: str, source_id: str) -> str:
        """1 ba_unit por spatial_unit (sem dados de holder ainda)."""
        cur.execute(
            "SELECT id FROM core.ba_unit WHERE spatial_unit_id = %s LIMIT 1",
            (spatial_unit_id,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            """
            INSERT INTO core.ba_unit (spatial_unit_id, source_id)
            VALUES (%s, %s)
            RETURNING id
            """,
            (spatial_unit_id, source_id),
        )
        return cur.fetchone()[0]

    def _replace_payment_options(self, cur, lot_id: str, options: list[dict]) -> None:
        """Idempotente: substitui todas as opções do lote (DELETE+INSERT)."""
        cur.execute("DELETE FROM core.payment_option WHERE lot_id = %s", (lot_id,))
        for opt in options:
            kind = opt.get("kind")
            if not kind:
                continue
            cur.execute(
                """
                INSERT INTO core.payment_option
                    (lot_id, kind, max_installments, min_down_payment_pct, notes)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    lot_id,
                    kind,
                    opt.get("max_installments"),
                    _to_decimal(opt.get("min_down_payment_pct")),
                    opt.get("notes"),
                ),
            )

    def _replace_encumbrances(
        self, cur, ba_unit_id: str, source_id: str, encs: list[dict]
    ) -> None:
        """Idempotente por (ba_unit, source): substitui só ônus do mesmo source."""
        cur.execute(
            "DELETE FROM core.encumbrance WHERE ba_unit_id = %s AND source_id = %s",
            (ba_unit_id, source_id),
        )
        for enc in encs:
            kind = enc.get("kind")
            if not kind:
                continue
            cur.execute(
                """
                INSERT INTO core.encumbrance
                    (ba_unit_id, kind, status, amount, description, source_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    ba_unit_id,
                    kind,
                    enc.get("status") or "declarado",
                    _to_decimal(enc.get("amount")),
                    enc.get("description"),
                    source_id,
                ),
            )

    # ------------------------------------------------------------------
    # Dedup canonical_link
    # ------------------------------------------------------------------

    def _link_canonical(
        self, cur, lot_id: str, source_kind: str, a: ItemAdapter
    ) -> None:
        """Inter-fontes dedup: associa lot do banco (secondary) ao lot do
        leiloeiro (canonical) quando match por (address_key + registry_key).

        Regras:
          - Se atual é banco e existe match não-banco → atual vira secondary.
          - Se atual é não-banco e existe match banco → match banco vira
            secondary, atual fica canonical (UPSERT por secondary_lot_id).
          - Se mesma source_kind dos dois lados → não faz dedup (mantém
            ambos como canônicos).
        """
        addr_key = _address_key(a.get("address") or {})
        reg_key = _registry_key(a.get("description") or "")
        # Sem chaves significativas, nada pra dedupar.
        if not addr_key and not reg_key:
            return

        # Busca outros lots com mesma chave. O lookup vai contra os dados
        # acabados de upsertar — ok porque _persist é dentro de 1 txn.
        cur.execute(
            """
            WITH cand AS (
              SELECT
                al.id              AS lot_id,
                src.source_kind    AS source_kind,
                core.unaccent_lite(
                  coalesce(ad.cep::text,'') || '|' ||
                  coalesce(ad.street_name,'') || '|' || coalesce(ad.number,'')
                )                  AS addr_key,
                (
                  SELECT (regexp_match(al.description,
                    'matr[ií]cula?[^0-9]{0,20}(?:n[ºo°.]?\\s*)?(\\d{1,3}(?:\\.\\d{3})*|\\d{3,8})',
                    'i'))[1]
                )                  AS reg_key
              FROM core.auction_lot al
              LEFT JOIN core.source src ON src.id = al.source_id
              LEFT JOIN core.lot_unit_link lu ON lu.lot_id = al.id
              LEFT JOIN core.spatial_unit su ON su.id = lu.spatial_unit_id
              LEFT JOIN core.address ad ON ad.id = su.address_id
              WHERE al.id <> %s
            )
            SELECT lot_id, source_kind
            FROM cand
            WHERE
              (CASE WHEN %s::text = '' THEN false
                    ELSE addr_key = core.unaccent_lite(%s::text) END)
              OR (CASE WHEN %s::text IS NULL THEN false
                       ELSE reg_key = %s::text END)
            LIMIT 5
            """,
            (lot_id, addr_key, addr_key, reg_key, reg_key),
        )
        rows = cur.fetchall() or []
        if not rows:
            return

        # Particiona em banks/non-banks.
        non_bank_other = next(((lid, sk) for lid, sk in rows if sk != "bank"), None)
        bank_other = next(((lid, sk) for lid, sk in rows if sk == "bank"), None)

        match_kind = "address+registry" if (addr_key and reg_key) else \
                     "registry" if reg_key else "address"
        confidence = 90 if (addr_key and reg_key) else 70 if reg_key else 55

        if source_kind == "bank" and non_bank_other:
            # Atual lot é banco; existe match leiloeiro → atual é secondary.
            self._insert_canonical_link(
                cur, canonical=non_bank_other[0], secondary=lot_id,
                match_kind=match_kind, confidence=confidence,
            )
        elif source_kind != "bank" and bank_other:
            # Atual lot é leiloeiro; existe match banco → banco é secondary.
            self._insert_canonical_link(
                cur, canonical=lot_id, secondary=bank_other[0],
                match_kind=match_kind, confidence=confidence,
            )

    def _insert_canonical_link(
        self,
        cur,
        canonical: str,
        secondary: str,
        match_kind: str,
        confidence: int,
    ) -> None:
        cur.execute(
            """
            INSERT INTO core.lot_canonical_link
                (canonical_lot_id, secondary_lot_id, match_kind, confidence)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (secondary_lot_id) DO UPDATE
              SET canonical_lot_id = EXCLUDED.canonical_lot_id,
                  match_kind       = EXCLUDED.match_kind,
                  confidence       = EXCLUDED.confidence
            """,
            (canonical, secondary, match_kind, confidence),
        )


# ---------------------------------------------------------------------------
# Helpers de address
# ---------------------------------------------------------------------------


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


def _address_key(addr: dict) -> str:
    """Chave determinística para dedup. Vazio quando endereço é insuficiente.

    Campos aceitos (em ordem de precedência): cep/zip, street_name/street, number.
    A SQL counterpart no DB usa exatamente cep + street_name + number
    (`core.unaccent_lite(cep || '|' || street_name || '|' || number)`).
    """
    if not addr:
        return ""
    cep = _normalize_cep(addr.get("cep") or addr.get("zip") or "")
    street = (addr.get("street_name") or addr.get("street") or "").strip().lower()
    number = str(addr.get("number") or "").strip().lower()
    if not cep and not (street and number):
        return ""
    raw = f"{cep or ''}|{_strip_accents(street)}|{number}"
    return raw.strip("| ")


def _registry_key(description: str) -> str | None:
    """Extrai número de matrícula CRI ('123.456' → '123456'). None se não bater."""
    if not description:
        return None
    m = _REGISTRY_RE.search(description)
    if not m:
        return None
    return m.group(1).replace(".", "")


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
