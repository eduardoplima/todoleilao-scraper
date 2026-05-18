#!/usr/bin/env bash
# Providers SaaS grandes (Soleon 116, S4B 43, leilao_pro 84) em série.
# Cada um aceita -a sites=all pra varrer todos os tenants.
#
# Idempotente: UPSERT por (source_id, source_lot_code).
# Exit 1 se NENHUM spider entregou items.

set -u
cd /app/scrapy_project || exit 2

LOG_DIR=/tmp
mkdir -p "$LOG_DIR"

# spider:args_extra
SPIDERS=(
    "soleon:-a sites=all"
    "s4b_digital:-a sites=all"
    "leilao_pro:-a sites=all"
)
TIMEOUT_PER_SPIDER=$((90 * 60))
TOTAL_NEW=0

for entry in "${SPIDERS[@]}"; do
    spider="${entry%%:*}"
    args="${entry#*:}"

    echo "[$(date -u +%FT%TZ)] STARTING $spider ($args; timeout ${TIMEOUT_PER_SPIDER}s)"

    # Foreground simples — output direto pra stdout (fly logs captura).
    # Antes era `nohup ... &` + `PID=$!`, mas o $! do bash referenciava
    # subshell que terminava no exec, fazendo o while loop sair sem dar
    # chance do scrapy nem iniciar.
    timeout --kill-after=60s "$TIMEOUT_PER_SPIDER" \
        scrapy crawl "$spider" $args -a incremental_only=true \
            -s LOG_LEVEL=INFO \
            -s CLOSESPIDER_TIMEOUT="$TIMEOUT_PER_SPIDER" \
            2>&1 || true

    AFTER_INTERVAL=$((TIMEOUT_PER_SPIDER / 60 + 5))
    NEW=$(python /app/scripts/spider_run_health.py --since-minutes "$AFTER_INTERVAL" 2>/dev/null | wc -l | tr -d ' ')
    TOTAL_NEW=$((TOTAL_NEW + NEW))
    echo "  $spider DONE (hosts ativos no batch: $NEW)"
done

echo "[$(date -u +%FT%TZ)] BATCH DONE hosts_with_new=$TOTAL_NEW"

# Refresh matviews pra propagar lots novos/atualizados pro front.
# Cron diário às 06:00 UTC é rede de segurança; este é o caminho principal.
echo "[$(date -u +%FT%TZ)] REFRESH matviews public_v1.*"
python -c "
import os, psycopg
with psycopg.connect(os.environ['SUPABASE_DB_URL'], autocommit=True) as c, c.cursor() as cur:
    cur.execute('REFRESH MATERIALIZED VIEW CONCURRENTLY public_v1.lot_search')
    cur.execute('REFRESH MATERIALIZED VIEW CONCURRENTLY public_v1.uf_stats')
    cur.execute('REFRESH MATERIALIZED VIEW CONCURRENTLY public_v1.municipality_stats')
print('refresh OK')
" 2>&1 | tail -3 || true

[ "$TOTAL_NEW" -gt 0 ] || exit 1
