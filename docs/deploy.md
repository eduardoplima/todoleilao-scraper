# Deploy — spider SOLEON em Fly.io + Supabase

Roteiro de bootstrap do **primeiro spider em produção**: SOLEON
(`scrapy crawl soleon`), persistindo em Supabase Postgres, agendado no
Fly.io com Machine diária.

## 1. Supabase — schema + extensões

1. Crie um projeto Supabase. Em **Project Settings → Database** copie a
   connection string **URI** (Session, não Pooler — runs longos
   precisam de conexão direta).
2. Habilite extensões necessárias (uma vez por projeto):
   ```bash
   psql "$SUPABASE_DB_URL" -c "CREATE EXTENSION IF NOT EXISTS postgis;"
   psql "$SUPABASE_DB_URL" -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
   psql "$SUPABASE_DB_URL" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
   psql "$SUPABASE_DB_URL" -c "CREATE EXTENSION IF NOT EXISTS btree_gist;"
   ```
3. Aplique o DDL principal:
   ```bash
   psql "$SUPABASE_DB_URL" -f sql/todoleilao_ddl.sql
   ```
   Se `core.hash_cpf` falhar pedindo pepper, configure por sessão:
   ```sql
   SET LOCAL "core.cpf_pepper" = '<sua chave>';
   ```
   Para o spider v1 não importa — não há extração de CPF.

## 2. Local — smoke test contra o Supabase

```bash
cp .env.example .env
# edite SUPABASE_DB_URL, CPF_PEPPER

set -a && source .env && set +a
cd scrapy_project
uv run scrapy crawl soleon -a sites=2 -s CLOSESPIDER_ITEMCOUNT=10
```

Deve aparecer no log:
```
SupabasePipeline: conectado em <host>
[soleon] INFO: event=soleon_lote_extracted ...
SupabasePipeline: N items persistidos, 0 falhas
```

Confirme no Supabase:
```sql
SELECT count(*) FROM core.scrape_event WHERE scraped_at > now() - interval '5 minutes';
SELECT count(*) FROM core.auction_lot;
SELECT count(*) FROM core.bid;
SELECT current_status, count(*) FROM core.auction_lot GROUP BY 1;
```

**Idempotência**: rode 2× e confirme que `count(*)` em `core.auction_lot`
fica estável (UPSERT por `(source_id, source_lot_code)`).

## 3. Docker — verificar imagem

```bash
docker build -t todoleilao-soleon .
docker run --rm --env-file .env todoleilao-soleon
```

Mesmo resultado do passo 2 (apenas `CLOSESPIDER_ITEMCOUNT` não é forçado;
o `SOLEON_SITES` env controla escala).

## 4. Fly.io — bootstrap

Pré-requisito: `flyctl` instalado e `fly auth login`.

```bash
# Cria o app (sem deploy ainda)
fly launch --no-deploy --copy-config --name todoleilao-soleon

# Secrets — não commitar
fly secrets set \
    SUPABASE_DB_URL="postgresql://..." \
    CPF_PEPPER="$(openssl rand -hex 32)"

# Build + push da imagem
fly deploy
```

Verifique:
```bash
fly status        # mostra app criado, sem máquinas rodando ainda
fly secrets list  # confirma SUPABASE_DB_URL e CPF_PEPPER setados
```

## 5. Primeira execução manual

```bash
fly machines run --rm . scrapy crawl soleon -a sites=2
fly logs                                         # acompanha
```

Confirme no Supabase como no passo 2. A flag `--rm` faz a Machine
ser destruída ao fim da execução (sem custo idle).

## 6. Agendar cron diário

```bash
fly machines run \
    --schedule daily \
    --region gru \
    --vm-size shared-cpu-1x \
    --vm-memory 256 \
    . scrapy crawl soleon -a sites=10
```

Verifique:
```bash
fly machines list
# Deve aparecer 1 Machine com `Schedule: daily`
```

A Machine inicia uma vez por dia (~UTC 0:00 padrão Fly), roda o spider,
encerra. Custo aproximado: 5min/dia × 30 dias × $0.0000022/s ≈ **US$
0.50/mês**.

Para outros horários (ex.: 6:00 BRT = 9:00 UTC para sites estarem mais
estáveis), use `cron(0 9 * * *)` em vez de `daily`:
```bash
fly machines update <machine-id> --schedule '0 9 * * *'
```

## 7. Validação T+1

24h depois:

```bash
fly machines list
# A Machine recorrente deve estar com `Last run: <timestamp>`

psql "$SUPABASE_DB_URL" -c "
  SELECT date_trunc('hour', scraped_at) AS hr, count(*)
  FROM core.scrape_event
  GROUP BY 1 ORDER BY 1 DESC LIMIT 5;
"
```

Devem aparecer 2+ grupos de timestamps separados por ~24h, confirmando
que o cron disparou pelo menos 1× automaticamente.

## 8. Troubleshooting comum

- **`SUPABASE_DB_URL ausente — pipeline inerte`**: secret não foi setado
  ou o env não chegou no container. `fly secrets list` para conferir.
- **`psycopg.errors.UndefinedTable: relation "core.source" does not exist`**:
  DDL não aplicado ou aplicado em outro schema. Confira com
  `psql -c "\dt core.*"`.
- **Spider trava em `robots.txt`**: alguns tenants SOLEON têm robots
  restritivos. O spider respeita por design (`ROBOTSTXT_OBEY=True`).
  Reduza `-a sites=` e investigue tenant por tenant.
- **`Out of memory` no Fly**: aumente para `shared-cpu-1x@512mb` em
  `fly.toml`. SOLEON em 116 sites simultâneos pode estourar 256MB.

## 9. Observação operacional (Fase 2)

- Logs: `fly logs --app todoleilao-soleon` — guarde em SaaS de
  preferência (Better Stack, Logtail) via Fly's syslog drain se quiser
  histórico além do retain default.
- Alerta de falha: criar uma Machine separada que faz health check
  semanal contra `core.scrape_event` com `parse_status='success'` ≥ 1
  nas últimas 48h; se não, manda webhook (Discord/Slack).
- Outros providers: replicar este roteiro com `scrapy crawl <provider>`
  conforme cada blueprint vira spider concreto.
