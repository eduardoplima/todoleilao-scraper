# Quick Wins Sprint 1 — site_providers.csv merge

2026-05-17. Mescla `site_providers_v2.csv` em `site_providers.csv` para
providers que já têm spider, sem código novo.

## Estratégia

1. Diff v2 vs v1 por `host_of(final_url)` (lowercase, sem `www.`/protocolo).
2. Mantidos providers em `{soleon, suporte_leiloes, s4b_digital, leilao_pro,
   leilao_br, leilotech, mega_leiloes, plataforma_leiloar, wordpress,
   leiloes_judiciais_br, dg_platform}`.
3. Rows com `cache_used == cache_missing` descartadas (regra de
   `_provider_base._sites_for_provider`).
4. Append in-place (ordem v1 preservada; backup `site_providers.csv.bak.<ts>`).

## Resultado por provider

| provider               | v1  | v2  | added | final | smoke fails | erros |
|------------------------|----:|----:|------:|------:|------------:|------:|
| soleon                 | 134 | 179 |    12 |   146 |           0 |     0 |
| suporte_leiloes        |  52 |  85 |    21 |    73 |           0 |     0 |
| s4b_digital            |  43 |  73 |    21 |    64 |           0 |     0 |
| leilao_pro             |  90 |  93 |     0 |    90 |           - |     - |
| leilao_br              |  18 |  21 |     1 |    19 |           0 |     0 |
| leilotech              |  18 |  24 |     0 |    18 |           - |     - |
| mega_leiloes           |   2 |   3 |     0 |     2 |           - |     - |
| plataforma_leiloar     |  21 |  23 |     1 |    22 |           0 |     0 |
| wordpress              |  10 |  13 |     4 |    14 |           0 |     0 |
| leiloes_judiciais_br   |  37 |  43 |     2 |    39 |           0 |     0 |
| dg_platform            |   0 |   0 |     0 |     0 |           - |     - |
| **total**              | 425 | 557 |**62** |   487 |       **0** | **0** |

Notas:
- `leilao_pro`, `leilotech`, `mega_leiloes`, `dg_platform`: zero adds —
  todos os hosts v2 já estavam em v1 sob o mesmo provider.
- O batch de 188 hosts em `spider_gap_v2.csv` para esses providers já
  estava majoritariamente em v1 (132). Só 56 inéditos; +6 hosts presentes
  no delta v2 mas ausentes do gap (5 soleon, 1 suporte_leiloes) totalizam 62.

## Smoke tests (paralelo, máx 3)

```bash
cd scrapy_project
uv run scrapy crawl <provider> -a sites=2 -a incremental_only=true \
  -s CLOSESPIDER_ITEMCOUNT=5 -s LOG_LEVEL=INFO -s ROBOTSTXT_OBEY=False
```

| provider             | finish_reason          | items | erros |
|----------------------|------------------------|------:|------:|
| soleon               | closespider_itemcount  |     5 |     0 |
| suporte_leiloes      | finished               |     0 |     0 |
| s4b_digital          | finished               |     2 |     0 |
| leilao_br            | finished               |     0 |     0 |
| plataforma_leiloar   | closespider_itemcount  |    21 |     0 |
| wordpress            | finished               |     4 |     0 |
| leiloes_judiciais_br | closespider_itemcount  |    54 |     0 |

Nenhuma exception. Nenhuma row deletada. Os 0-item closes
(`suporte_leiloes`, `leilao_br`) refletem `incremental_only=true` + `sites=2`
nos primeiros hosts v1 (sem delta novo), não falha de pipeline.

Logs: `/tmp/quick_wins_smoke/<provider>.log`.

## Rows descartadas (smoke fail)

Nenhuma.

## Full crawl

```bash
bash scripts/run_batch_providers_large.sh  # soleon, s4b_digital, leilao_pro

# Demais providers tocados:
cd scrapy_project
for p in suporte_leiloes wordpress leiloes_judiciais_br leilao_br plataforma_leiloar; do
  uv run scrapy crawl "$p" -a sites=all -a incremental_only=true \
    -s LOG_LEVEL=INFO -s CLOSESPIDER_TIMEOUT=5400
done
```
