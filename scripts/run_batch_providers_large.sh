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

    nohup uv run scrapy crawl "$spider" $args \
        -s LOG_LEVEL=INFO \
        -s CLOSESPIDER_TIMEOUT="$TIMEOUT_PER_SPIDER" \
        > "$LOG_DIR/batch_${spider}.log" 2>&1 &
    PID=$!

    HARD=$(( $(date +%s) + TIMEOUT_PER_SPIDER + 300 ))
    while kill -0 "$PID" 2>/dev/null; do
        if [ "$(date +%s)" -ge "$HARD" ]; then
            kill "$PID" 2>/dev/null; sleep 10; kill -9 "$PID" 2>/dev/null
            echo "  $spider HARD-KILLED"
            break
        fi
        sleep 60
    done

    AFTER_INTERVAL=$((TIMEOUT_PER_SPIDER / 60 + 5))
    NEW=$(python /app/scripts/spider_run_health.py --since-minutes "$AFTER_INTERVAL" 2>/dev/null | wc -l | tr -d ' ')
    TOTAL_NEW=$((TOTAL_NEW + NEW))
    echo "  $spider DONE (hosts ativos no batch: $NEW)"
done

echo "[$(date -u +%FT%TZ)] BATCH DONE hosts_with_new=$TOTAL_NEW"
[ "$TOTAL_NEW" -gt 0 ] || exit 1
