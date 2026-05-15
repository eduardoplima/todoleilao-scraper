# Runbook: scraping contínuo via Fly.io + GitHub Actions

Sequência de comandos pra deploy do novo fluxo (8 fases). Cada fase é
independente; cada smoke test valida antes de ativar schedule.

## Pré-requisitos

- `fly` CLI logado (`fly auth login`).
- `gh` CLI logado e secret `FLY_API_TOKEN` setado no repo:
  ```bash
  fly tokens create deploy -x 8760h     # 1 ano
  gh secret set FLY_API_TOKEN --body '<token>'
  ```
- `.env` local com `SUPABASE_DB_URL`, `CPF_PEPPER`.

## Fase 0 — Imagem com Playwright

```bash
fly deploy -a todoleilao-soleon
# build ~5min (apt + playwright install chromium ~400MB)
```

Smoke:
```bash
fly machines run --rm -a todoleilao-soleon --process spider \
  -e SOLEON_SITES=2 registry.fly.io/todoleilao-soleon:latest
# valida: scrapy crawl soleon com 2 tenants. Sucesso = lots novos no DB.
```

## Fase 1 — Bancos leves

Smoke local:
```bash
cd scrapy_project
uv run scrapy crawl bradesco -s CLOSESPIDER_ITEMCOUNT=3
uv run scrapy crawl banco_brasil -s CLOSESPIDER_ITEMCOUNT=3
```

Smoke remoto:
```bash
fly machines run --rm -a todoleilao-soleon --process banks-simple \
  registry.fly.io/todoleilao-soleon:latest
```

Disparar workflow manualmente antes de ativar schedule:
```bash
gh workflow run cron-banks-simple.yml
gh run watch
```

## Fase 2 — Geocoder

Smoke:
```bash
fly machines run --rm -a todoleilao-soleon --process geocode \
  -e GEOCODE_BATCH_LIMIT=500 registry.fly.io/todoleilao-soleon:latest
# 500 endereços × 1req/s = ~8min
```

Workflow:
```bash
gh workflow run cron-geocode.yml
```

## Fase 3 — Providers médios

```bash
gh workflow run cron-providers-medium.yml
gh run watch
```

## Fase 4 — Providers grandes

```bash
gh workflow run cron-providers-large.yml
# Cuidado: ~4h. Se OOM em s4b_digital (Playwright), promover process
# pra VM dedicada no fly.toml:
#   [[vm]]
#     size = "shared-cpu-2x"
#     memory = "2048mb"
#     processes = ["providers-large"]
```

## Fase 5 — Sites próprios

```bash
gh workflow run cron-proprio-html.yml
```

## Fase 6 — Caixa app dedicado

```bash
# 6.1 Criar app
fly launch --no-deploy --copy-config --config fly.caixa.toml --name todoleilao-caixa

# 6.2 Secrets
fly secrets set \
  SUPABASE_DB_URL="$SUPABASE_DB_URL" \
  CPF_PEPPER="$CPF_PEPPER" \
  -a todoleilao-caixa

# 6.3 Deploy
fly deploy --config fly.caixa.toml -a todoleilao-caixa

# 6.4 Smoke UF pequena (<30min)
fly machines run --rm --config fly.caixa.toml -a todoleilao-caixa \
  --process caixa-uf-day -e CAIXA_UF=AC \
  registry.fly.io/todoleilao-caixa:latest

# 6.5 Smoke SP completo via workflow (aceitar 10h+)
gh workflow run cron-caixa-uf.yml -f uf=SP
gh run watch

# 6.6 Validar no DB
psql "$SUPABASE_DB_URL" -c "
SELECT short_name, last_24h_count
FROM core.spider_run_health
WHERE short_name = 'venda-imoveis.caixa.gov.br';
"
```

## Fase 7 — Observabilidade SQL

```bash
psql "$SUPABASE_DB_URL" -f sql/spider_run_health.sql
# Roda 1x manual pra popular log do dia
psql "$SUPABASE_DB_URL" -c "SELECT core.capture_spider_health();"
```

Consulta operacional:
```sql
-- Spiders ativos sem lots em 24h
SELECT short_name, total_lots, last_lot_at
FROM core.spider_run_health
WHERE total_lots > 100 AND last_24h_count = 0
ORDER BY last_lot_at;

-- Tendência por spider (últimos 14d)
SELECT short_name, day, lots
FROM core.spider_health_log
WHERE day > current_date - 14
ORDER BY short_name, day DESC;
```

## Fase 8 — Cleanup

- Validar com `fly billing show -o personal | grep todoleilao` (após 1 semana).
- `gh run list --limit 50` pra ver execuções dos crons.
- Remover do `scripts/run_pending_spiders.sh` o caminho hardcoded de
  `/Users/eduardo/...` (script é dev-local apenas).

## Rollback / pausar

Pausar 1 cron específico:
```bash
gh workflow disable cron-caixa-uf.yml
```

Pausar tudo:
```bash
for w in cron-caixa-uf cron-caixa-refazer cron-providers-large \
         cron-providers-medium cron-proprio-html cron-banks-simple \
         cron-geocode; do
  gh workflow disable "$w.yml"
done
```

## Custos esperados

| Job | h/mês | VM | $/mês |
|---|---|---|---|
| caixa-uf-day | 240 | perf-1x 2GB | $29 |
| caixa-refazer | 8 | perf-1x 2GB | $1 |
| providers-large | 120 | shared 1GB | $2.6 |
| providers-medium | 45 | shared 1GB | $1 |
| proprio-html | 6 | shared 1GB | $0.1 |
| banks-simple | 60 | shared 1GB | $1.3 |
| geocode (×2) | 84 | shared 512MB | $1.2 |
| **Total** | | | **~$36** |

Acima do alvo $25 — mitigação se Caixa SP for ~6h (não 8h) cai pra ~$28.
Se necessário cortar mais: reduzir Caixa rotação pra 4 UFs/semana.
