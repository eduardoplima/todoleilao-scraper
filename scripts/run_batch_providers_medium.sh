#!/usr/bin/env bash
# Providers SaaS médios (5-30 tenants cada). 45min timeout cada — cabem
# na janela de ~3h total. Idempotentes via UPSERT.

set -u
cd /app/scrapy_project || exit 2

LOG_DIR=/tmp
mkdir -p "$LOG_DIR"

SPIDERS=(
    "suporte_leiloes:-a sites=all"
    "leiloes_judiciais_br:"
    "leilao_br:-a sites=all"
    "leilotech:-a sites=all"
    "mega_leiloes:-a sites=all"
    "plataforma_leiloar:-a sites=all"
    "dg_platform:"
    "degrau_publicidade:-a sites=all"
    "inertia_laravel_leiloes:-a sites=all"
    "portal_zuk:-a sites=1"
    "leiloesbr:-a sites=all"
)
TIMEOUT_PER_SPIDER=$((45 * 60))
TOTAL_NEW=0

for entry in "${SPIDERS[@]}"; do
    spider="${entry%%:*}"
    args="${entry#*:}"

    echo "[$(date -u +%FT%TZ)] STARTING $spider ($args; timeout ${TIMEOUT_PER_SPIDER}s)"

    # Foreground via `timeout` (vide comentário em run_batch_providers_large.sh).
    timeout --kill-after=60s "$TIMEOUT_PER_SPIDER" \
        scrapy crawl "$spider" $args -a incremental_only=true \
            -s LOG_LEVEL=INFO \
            -s CLOSESPIDER_TIMEOUT="$TIMEOUT_PER_SPIDER" \
            2>&1 || true

    echo "  $spider DONE"
    TOTAL_NEW=$((TOTAL_NEW + 1))
done

AFTER=$(python /app/scripts/spider_run_health.py --since-minutes 300 2>/dev/null | wc -l | tr -d ' ')
echo "[$(date -u +%FT%TZ)] BATCH DONE hosts_with_new=$AFTER"
[ "$AFTER" -gt 0 ] || exit 1
