"""Modelos Pydantic v2 para o item piloto produzido pelo `site-recon-pilot`.

Os campos refletem decisões já tomadas no `sql/todoleilao_ddl.sql` (esquema
`core.*`) projetadas para a Fase 1 (recon). A Fase 2 (normalização IBGE +
geocoding + dedup) usa um superset destes campos.

Convenções:
- Dinheiro em `Decimal` (string `"123456.78"`); nunca float.
- Datas em `datetime` timezone-aware (ISO 8601, idealmente `-03:00`).
- URLs em `HttpUrl` — Pydantic recusa esquemas inválidos.
- Vocabulários pequenos via `Literal`; vocabulários grandes (UF, CEP)
  via regex.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

PropertyType = Literal[
    "apartamento",
    "casa",
    "terreno",
    "comercial",
    "rural",
    "outro",
]

AuctionStatus = Literal[
    "ativo",
    "encerrado",
    "arrematado",
    "cancelado",
    "suspenso",
    "desconhecido",
]

DocumentKind = Literal[
    "edital",
    "matricula",
    "laudo",
    "certidao",
    "outro",
]


class PilotAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(min_length=1)
    street_name: str | None = None
    number: str | None = None
    complement: str | None = None
    district: str | None = None
    municipality_name: str | None = None
    uf: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    cep: str | None = Field(default=None, pattern=r"^\d{5}-?\d{3}$")


class PilotDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DocumentKind
    url: HttpUrl
    label: str | None = None


class PilotImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    is_thumbnail: bool = False


class PilotRound(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_number: int = Field(ge=1, le=9)
    scheduled_at: datetime | None = None
    minimum_bid_brl: Decimal | None = None
    status_raw: str | None = None

    @field_validator("scheduled_at")
    @classmethod
    def _tz_aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("scheduled_at precisa ser timezone-aware (ISO 8601 com offset)")
        return v


class PilotBid(BaseModel):
    """Lance individual no histórico de um leilão encerrado.

    SOFT por design: nem todo provider expõe histórico publicamente. PII
    (CPF, nome PF) deve ser redigida em `bidder_raw` antes de serializar
    — ver pilot-schema/closed-auction-bids para padrões.
    """

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    value_brl: Decimal
    bidder_raw: str | None = None

    @field_validator("timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("bid timestamp precisa ser timezone-aware (ISO 8601 com offset)")
        return v


class PilotItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auctioneer_slug: str = Field(min_length=1)
    source_listing_url: HttpUrl
    source_lot_url: HttpUrl

    title: str = Field(min_length=1)
    description: str | None = None
    property_type: PropertyType | None = None

    address: PilotAddress

    area_sqm: Decimal | None = None
    total_area_sqm: Decimal | None = None
    market_value_brl: Decimal | None = None

    rounds: list[PilotRound] = Field(default_factory=list)
    auction_status: AuctionStatus

    bids: list[PilotBid] = Field(default_factory=list)

    images: list[PilotImage] = Field(default_factory=list)
    documents: list[PilotDocument] = Field(default_factory=list)
    encumbrances_raw: list[str] = Field(default_factory=list)

    scraped_at: datetime
    parser_notes: str | None = None

    @field_validator("scraped_at")
    @classmethod
    def _scraped_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("scraped_at precisa ser timezone-aware (ISO 8601 com offset)")
        return v
