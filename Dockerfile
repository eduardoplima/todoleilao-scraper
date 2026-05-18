# syntax=docker/dockerfile:1.7

# ----- Stage 1: builder -----------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1

# uv via pip (versão fixa). Alternativa: COPY --from=ghcr.io/astral-sh/uv:0.5.X
RUN pip install --no-cache-dir uv==0.5.7

WORKDIR /app

# Resolve deps primeiro pra cachear bem com bind-mount de pyproject/uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project --frozen

# Código da aplicação. Mantemos só o essencial pra runtime.
COPY scrapy_project/ ./scrapy_project/
COPY validator/ ./validator/
COPY specs/_providers/ ./specs/_providers/
COPY data/intermediate/site_providers.csv ./data/intermediate/site_providers.csv
COPY discovery/ ./discovery/
COPY scripts/ ./scripts/

# ----- Stage 2: runtime -----------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Pacotes runtime:
#   - libxml2/libxslt: parser lxml (BeautifulSoup)
#   - ca-certificates: HTTPS
#   - Demais libs: dependências do Chromium headless (Caixa Radware, s4b CF,
#     bradesco Hallo). playwright install --with-deps abaixaria o set completo
#     mas pesa ~150MB extra; lista enxuta cobre o necessário pro headless.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates libxml2 libxslt1.1 \
        libnss3 libatk-bridge2.0-0 libxkbcommon0 libgbm1 libasound2 \
        libxcomposite1 libxdamage1 libxrandr2 libxfixes3 libpango-1.0-0 \
        libcairo2 libdrm2 fonts-liberation \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app /app

# Instala o binário do Chromium em /ms-playwright (compartilhado com o user
# `spider` via chown abaixo). Roda ANTES do useradd pra cachear no layer.
RUN /app/.venv/bin/playwright install chromium

# Executa como non-root. ms-playwright precisa ser readable pelo spider.
RUN useradd -m -u 1000 spider \
 && chown -R spider:spider /app /ms-playwright
USER spider

WORKDIR /app

# Variáveis configuráveis em runtime (sobrescrever via fly secrets/env):
#   SUPABASE_DB_URL    — DSN postgresql:// do projeto Supabase
#   CPF_PEPPER         — chave HMAC para core.hash_cpf (Privacy by Design)
#   SOLEON_SITES       — quantos sites SOLEON crawlear (default 5)
#   GEOCODE_BATCH_LIMIT — máx endereços geocodificados por execução (default 5000)
ENV SOLEON_SITES=5 \
    GEOCODE_BATCH_LIMIT=5000

# Default: rodar o spider SOLEON. Para o worker de geocoding, override
# o command em runtime — vide [processes] em fly.toml.
CMD ["sh", "-c", "cd /app/scrapy_project && scrapy crawl soleon -a sites=${SOLEON_SITES}"]
