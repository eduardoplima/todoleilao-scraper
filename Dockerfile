# syntax=docker/dockerfile:1.7

# ----- Stage 1: builder -----------------------------------------------------
FROM python:3.13-slim AS builder

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

# ----- Stage 2: runtime -----------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

# Pacotes mínimos: libxml2/libxslt para lxml, ca-certificates para HTTPS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates libxml2 libxslt1.1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app /app

# Executa como non-root
RUN useradd -m -u 1000 spider && chown -R spider:spider /app
USER spider

WORKDIR /app/scrapy_project

# Variáveis configuráveis em runtime (sobrescrever via fly secrets/env):
#   SUPABASE_DB_URL  — DSN postgresql:// do projeto Supabase
#   CPF_PEPPER       — chave HMAC para core.hash_cpf (Privacy by Design)
#   SOLEON_SITES     — quantos sites SOLEON crawlear (default 5)
ENV SOLEON_SITES=5

# Default: rodar SOLEON. Override em fly.toml ou docker run.
CMD ["sh", "-c", "scrapy crawl soleon -a sites=${SOLEON_SITES}"]
