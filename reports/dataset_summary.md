# Dataset summary — `data/processed/properties.parquet`

Snapshot do consolidado de **259** imóveis raspados pelos 6 leiloeiros ativos no `scripts/run_all.py`. Atualizar com `uv run python -m scripts.build_dataset_summary`.

## Total por leiloeiro

| leiloeiro | itens |
|:---|---:|
| cassianoleiloes | 62 |
| moacira_tegoni_goedert | 59 |
| oaleiloes | 56 |
| mullerleiloes | 51 |
| rechleiloes | 30 |
| projudleiloes | 1 |

## Distribuição por estado

| UF | itens | % |
|:---|---:|---:|
| RS | 69 | 26.6% |
| CE | 68 | 26.3% |
| GO | 26 | 10.0% |
| AL | 18 | 6.9% |
| BA | 14 | 5.4% |
| DF | 13 | 5.0% |
| SC | 8 | 3.1% |
| AM | 6 | 2.3% |
| MG | 6 | 2.3% |
| ES | 4 | 1.5% |
| RJ | 2 | 0.8% |
| PR | 1 | 0.4% |
| MT | 1 | 0.4% |

## Distribuição por tipo de imóvel

| property_type | itens | % |
|:---|---:|---:|
| terreno | 105 | 40.5% |
| apartamento | 99 | 38.2% |
| casa | 30 | 11.6% |
| (none) | 18 | 6.9% |
| rural | 5 | 1.9% |
| comercial | 2 | 0.8% |

## Distribuição por faixa de preço (`minimum_bid`)

| faixa | itens | % do total |
|:---|---:|---:|
| ≤ 50k | 20 | 7.7% |
| 50k–150k | 117 | 45.2% |
| 150k–300k | 44 | 17.0% |
| 300k–600k | 29 | 11.2% |
| 600k–1,5M | 22 | 8.5% |
| > 1,5M | 20 | 7.7% |
| (sem preço) | 7 | — |

_Estatísticas:_ mín = R$ 0.75, mediana = R$ 128,370.04, média = R$ 576,574.09, máx = R$ 22,663,978.20.

## Data quality — % preenchimento por coluna

| coluna | fill rate |
|:---|---:|
| url | 100.0% |
| auctioneer | 100.0% |
| source_listing_url | 100.0% |
| title | 100.0% |
| description | 100.0% |
| scraped_at | 100.0% |
| minimum_bid | 97.3% |
| property_type | 93.1% |
| address | 91.1% |
| images | 80.3% |
| market_value | 74.9% |
| discount_pct | 73.4% |
| total_area_sqm | 62.5% |
| area_sqm | 36.7% |
| bedrooms | 30.9% |
| parking_spots | 24.3% |
| documents | 21.6% |
| bathrooms | 14.7% |
| auction_phase | 0.4% |
| status | 0.4% |

## Top 10 gaps de qualidade

Score = `(1 - fill_rate) × weight`. Weight reflete importância no schema canônico do CLAUDE.md.

| coluna | fill rate | weight | impact |
|:---|---:|---:|---:|
| auction_phase | 0.4% | 4 | 3.98 |
| status | 0.4% | 3 | 2.99 |
| bathrooms | 14.7% | 3 | 2.56 |
| area_sqm | 36.7% | 4 | 2.53 |
| bedrooms | 30.9% | 3 | 2.07 |
| market_value | 74.9% | 7 | 1.76 |
| discount_pct | 73.4% | 6 | 1.6 |
| documents | 21.6% | 2 | 1.57 |
| parking_spots | 24.3% | 2 | 1.51 |
| total_area_sqm | 62.5% | 4 | 1.5 |

### Onde mexer primeiro

- **`auction_phase`** (0.4% preenchido) — impact 3.98.
- **`status`** (0.4% preenchido) — impact 2.99.
- **`bathrooms`** (14.7% preenchido) — impact 2.56.
- **`area_sqm`** (36.7% preenchido) — impact 2.53.
- **`bedrooms`** (30.9% preenchido) — impact 2.07.
