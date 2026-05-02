"""Build pilot_item.json from the Livewire snapshot for lote 33128.

Sale data + structured fields come from `snapshot_0.json` (extracted from
`pilot_source.html`'s `wire:snapshot` attribute).
"""
from __future__ import annotations

import html as html_mod
import json
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from pathlib import Path

HERE = Path(__file__).parent
snap = json.load(open(HERE / "snapshot_0.json"))["data"]
lote = snap["lote"][0]
leilao = lote["leilao"][0]

# table_rows is a list of [label/value pairs, meta]
rows: dict[str, str] = {}
for row in lote["table_rows"][0]:
    if isinstance(row, list) and row and isinstance(row[0], dict):
        rows[row[0]["label"]] = row[0]["value"]

print("Parsed rows:", list(rows.keys()))

# Round info from the Lance inicial HTML
import re

lance_html = rows["Lance inicial:"]
# Strip HTML tags first since they sit between label and date.
lance_text = re.sub(r"<[^>]+>", " ", lance_html)
lance_text = html_mod.unescape(lance_text)
lance_text = re.sub(r"\s+", " ", lance_text).strip()
# Now: "1º. LEILÃO: Sex, 10/04/2026 - 10:00h - R$ 470.700,91 2º. LEILÃO: ..."
round_pattern = re.compile(
    r"(\d+)º?\.?\s*LEIL[ÃA]O:\s*[A-Za-zÀ-ÿ]+,?\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{1,2}:\d{2})h?\s*-\s*R\$\s*([\d.,]+)",
    re.IGNORECASE,
)
sale_pattern = re.compile(r"vendido pelo valor de:?\s*R\$\s*([\d.,]+)", re.IGNORECASE)

rounds = []
for m in round_pattern.finditer(lance_text):
    rn = int(m.group(1))
    date_s = m.group(2)
    time_s = m.group(3)
    bid_s = m.group(4)
    dt = datetime.strptime(f"{date_s} {time_s}", "%d/%m/%Y %H:%M").replace(
        tzinfo=ZoneInfo("America/Sao_Paulo")
    )
    bid_decimal = Decimal(bid_s.replace(".", "").replace(",", "."))
    rounds.append(
        {
            "round_number": rn,
            "scheduled_at": dt.isoformat(),
            "minimum_bid_brl": str(bid_decimal),
            "status_raw": f"{rn}ª praça encerrada",
        }
    )

# Add the sale outcome as final round status_raw
sale_match = sale_pattern.search(lance_text)
sale_value = None
if sale_match:
    sale_value = Decimal(sale_match.group(1).replace(".", "").replace(",", "."))
maior_lance = rows.get("Maior Lance:", "")
apelido = rows.get("Apelido:", "")
total_lances = rows.get("Total de lances:", "")
if rounds:
    rounds[-1]["status_raw"] = (
        f"Arrematado por {apelido} — {maior_lance} (Total de lances: {total_lances})"
    )

print("rounds:", rounds)
print("sale_value:", sale_value)

# Status banner = VENDIDO -> arrematado
banner = lote["status_banner"][0]
print("banner:", banner)
status_text = banner.get("text", "").lower()
auction_status = "arrematado" if "vendido" in status_text else "encerrado"

# Address: pull raw text from description and structured pieces
desc_html = lote["description_html"]
# decode entities
desc_text = html_mod.unescape(re.sub(r"<[^>]+>", " ", desc_html))
desc_text = re.sub(r"\s+", " ", desc_text).strip()
# Find the LOCALIZAÇÃO line. The text contains "n." abbreviations,
# so we need to terminate on a CEP (\d{5}-\d{3}) or on the next ALL-CAPS
# section header (e.g. "AVALIAÇÃO:").
loc_match = re.search(
    r"LOCALIZA[ÇC][ÃA]O:\s*(.+?(?:\d{5}-\d{3}\.?|(?=\s+[A-ZÇÃÁÉÍÓÚ]{4,}:)))",
    desc_text,
    re.IGNORECASE,
)
loc_raw = loc_match.group(1).strip() if loc_match else ""
print("LOC:", loc_raw)
# CEP
cep_m = re.search(r"\b(\d{5}-\d{3})\b", loc_raw)
cep = cep_m.group(1) if cep_m else None

# Market value: "R$ 470.700,91"
aval = rows["Valor da avaliação:"]
market_decimal = Decimal(aval.replace("R$", "").strip().replace(".", "").replace(",", "."))

# Property type: from category breadcrumb / lote categoria; here we know it's apartamento
title = lote["title"]
prop_type = "apartamento" if "apartamento" in title.lower() else "outro"

# Area: "53,13 m²" útil; "83,07 m²" total
area_m = re.search(r"([\d.,]+)\s*m[²2]\s*,?\s*mais\s*([\d.,]+)\s*m[²2]\s*,\s*de\s*[áa]rea comum", desc_text, re.IGNORECASE)
useful = total = None
if area_m:
    useful = Decimal(area_m.group(1).replace(",", "."))
    # total = útil + comum
    total_m = re.search(r"totalizando\s*([\d.,]+)\s*m[²2]", desc_text, re.IGNORECASE)
    if total_m:
        total = Decimal(total_m.group(1).replace(",", "."))

print("useful", useful, "total", total)

# Images
def collect_images(x, out):
    if isinstance(x, list):
        for el in x:
            collect_images(el, out)
    elif isinstance(x, dict) and "image" in x and "thumb" in x:
        out.append(x)


imgs_flat = []
collect_images(lote["images"], imgs_flat)

images = [{"url": im["original"], "is_thumbnail": False} for im in imgs_flat]
print("images:", len(images))

# Documents
docs = []
def collect_docs(x, out):
    if isinstance(x, list):
        for el in x:
            collect_docs(el, out)
    elif isinstance(x, dict) and "url" in x and "label" in x and ".pdf" in x["url"].lower():
        out.append(x)


docs_flat = []
collect_docs(lote["documents"], docs_flat)
for doc in docs_flat:
    label_low = doc["label"].lower()
    if "edital" in label_low:
        kind = "edital"
    elif "matr" in label_low:
        kind = "matricula"
    elif "laudo" in label_low or "avalia" in label_low:
        kind = "laudo"
    elif "certid" in label_low or "ônus" in label_low or "onus" in label_low:
        kind = "certidao"
    else:
        kind = "outro"
    docs.append({"kind": kind, "url": doc["url"], "label": doc["label"]})

# also actions['EDITAL'] link
def collect_actions(x, out):
    if isinstance(x, list):
        for el in x:
            collect_actions(el, out)
    elif isinstance(x, dict) and "url" in x and "label" in x:
        out.append(x)


acts = []
collect_actions(lote.get("actions") or [], acts)
for act in acts:
    if act["label"].lower() == "edital":
        docs.append({"kind": "edital", "url": act["url"], "label": "EDITAL"})

print("docs:", docs)

# Build description (decoded + truncated; PII redact pass — no CPF/PF detected)
description = desc_text[:2000]
# Quick PII scan
cpf_re = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
redacted_count = 0
if cpf_re.search(description):
    description = cpf_re.sub("[CPF]", description)
    redacted_count += 1

source_lot_url = lote["canonical"]
source_listing_url = "https://topoleiloes.com.br/encerrados"
scraped_at = datetime.now(tz=ZoneInfo("America/Sao_Paulo")).isoformat()

addr_raw = loc_raw or "Av. Dom Pedro I, 219, Cambuci, São Paulo/SP"

item = {
    "auctioneer_slug": "guilherme-eduardo-stutz-toporoski",
    "source_listing_url": source_listing_url,
    "source_lot_url": source_lot_url,
    "title": title,
    "description": description,
    "property_type": prop_type,
    "address": {
        "raw_text": addr_raw,
        "street_name": "Av. Dom Pedro I",
        "number": "219",
        "complement": "Apartamento 112",
        "district": "Cambuci",
        "municipality_name": "São Paulo",
        "uf": "SP",
        "cep": cep,
    },
    "area_sqm": str(useful) if useful else None,
    "total_area_sqm": str(total) if total else None,
    "market_value_brl": str(market_decimal),
    "rounds": rounds,
    "auction_status": auction_status,
    "bids": [],
    "images": images,
    "documents": docs,
    "encumbrances_raw": [],
    "scraped_at": scraped_at,
    "parser_notes": (
        "Provider leilotech (Laravel + Livewire, CDN cdn.leilotech.workers.dev). "
        "Estado completo do lote em <... wire:snapshot=\"...\"> no HTML inicial — "
        "Livewire/Volt JSON inline; nenhuma chamada XHR adicional necessária. "
        "Histórico de lances NÃO exposto publicamente: snapshot só traz "
        "agregados (Maior Lance, Apelido vencedor, Total de lances). bids=[] por "
        "design. status final em rounds[-1].status_raw."
    ),
}

# Drop optional empty
if item["description"] is None:
    item.pop("description")

(HERE / "pilot_item.json").write_text(
    json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("Wrote pilot_item.json")
