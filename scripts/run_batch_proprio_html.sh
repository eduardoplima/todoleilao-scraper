#!/usr/bin/env bash
# Sites próprios single-tenant em proprio_html_specific/. Descoberta
# dinâmica via `scrapy list` filtrado.
#
# Idempotente. Timeout curto (5min) — sites pequenos.

set -u
cd /app/scrapy_project || exit 2

LOG_DIR=/tmp
mkdir -p "$LOG_DIR"

# Lista todos os spiders e filtra os que importam de proprio_html_specific.
# Alternativa: hardcoded list — mantemos dinâmico pra absorver novos
# spiders sem mexer no script.
mapfile -t SPIDERS < <(uv run scrapy list 2>/dev/null | grep -vE '^(soleon|s4b_digital|leilao_pro|leilao_br|leilotech|suporte_leiloes|leiloes_judiciais_br|mega_leiloes|plataforma_leiloar|dg_platform|wordpress|degrau_publicidade|caixa|bradesco|santander|banco_brasil|dummy|playwright_generic|base|cassiano|moacira|muller|rech|oaleiloes|projud|sishp|frazao|leiloesweb|bomvalor|leiloesbr|palacio_dos_leiloes|sodre_santoro|sodresantoro)$')

if [ "${#SPIDERS[@]}" -eq 0 ]; then
    echo "[$(date -u +%FT%TZ)] sem spiders proprio_html elegíveis"
    exit 1
fi

echo "[$(date -u +%FT%TZ)] proprio-html batch — ${#SPIDERS[@]} spiders"

TIMEOUT_PER_SPIDER=$((5 * 60))   # 5min
COUNT_OK=0
COUNT_FAIL=0

for spider in "${SPIDERS[@]}"; do
    [ -z "$spider" ] && continue

    nohup uv run scrapy crawl "$spider" -a incremental_only=true \
        -s LOG_LEVEL=WARNING \
        -s CLOSESPIDER_TIMEOUT="$TIMEOUT_PER_SPIDER" \
        > "$LOG_DIR/batch_${spider}.log" 2>&1 &
    PID=$!

    HARD=$(( $(date +%s) + TIMEOUT_PER_SPIDER + 60 ))
    while kill -0 "$PID" 2>/dev/null; do
        if [ "$(date +%s)" -ge "$HARD" ]; then
            kill "$PID" 2>/dev/null; sleep 3; kill -9 "$PID" 2>/dev/null
            COUNT_FAIL=$((COUNT_FAIL + 1))
            echo "  $spider HARD-KILLED"
            break
        fi
        sleep 15
    done

    if kill -0 "$PID" 2>/dev/null; then
        :  # killed above
    else
        wait "$PID" 2>/dev/null
        rc=$?
        if [ "$rc" -eq 0 ]; then
            COUNT_OK=$((COUNT_OK + 1))
        else
            COUNT_FAIL=$((COUNT_FAIL + 1))
        fi
    fi
done

AFTER=$(python /app/scripts/spider_run_health.py --since-minutes 180 2>/dev/null | wc -l | tr -d ' ')
echo "[$(date -u +%FT%TZ)] BATCH DONE ok=$COUNT_OK fail=$COUNT_FAIL hosts_with_new=$AFTER"
[ "$AFTER" -gt 0 ] || exit 1
