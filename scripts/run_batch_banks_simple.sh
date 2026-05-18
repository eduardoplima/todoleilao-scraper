#!/usr/bin/env bash
# Roda em série os spiders dos bancos credores sem WAF agressivo.
# Santander está fora (Akamai bloqueia headless). Caixa é app separado.
#
# Idempotente: spiders fazem UPSERT por (source_id, source_lot_code).
# Exit 1 se TODOS os spiders inseriram 0 lots (degradação total).

set -u
cd /app/scrapy_project || exit 2

LOG_DIR=/tmp
mkdir -p "$LOG_DIR"

SPIDERS=(bradesco banco_brasil)
TIMEOUT_PER_SPIDER=$((90 * 60))   # 90min
TOTAL_NEW=0

for spider in "${SPIDERS[@]}"; do
    echo "[$(date -u +%FT%TZ)] STARTING $spider (timeout ${TIMEOUT_PER_SPIDER}s)"
    BEFORE=$(python /app/scripts/spider_run_health.py --since-minutes 1 --host "${spider}.com.br" 2>/dev/null || echo 0)

    # Foreground via `timeout` (vide comentário em run_batch_providers_large.sh).
    timeout --kill-after=60s "$TIMEOUT_PER_SPIDER" \
        scrapy crawl "$spider" -a incremental_only=true \
            -s LOG_LEVEL=INFO \
            -s CLOSESPIDER_TIMEOUT="$TIMEOUT_PER_SPIDER" \
            2>&1 || true

    AFTER_INTERVAL=$((TIMEOUT_PER_SPIDER / 60 + 5))
    NEW=$(python /app/scripts/spider_run_health.py --since-minutes "$AFTER_INTERVAL" 2>/dev/null | awk -v sp="$spider" '$1 ~ sp {sum+=$2} END {print sum+0}')
    TOTAL_NEW=$((TOTAL_NEW + NEW))
    echo "  $spider DONE: +$NEW lots"
done

echo "[$(date -u +%FT%TZ)] BATCH DONE total_new=$TOTAL_NEW"
[ "$TOTAL_NEW" -gt 0 ] || exit 1
