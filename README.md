# Todo Leilão Scraper

Pipeline de raspagem de imóveis em leilão a partir de leiloeiros oficiais brasileiros, partindo da lista pública mantida pelo INNLEI.

A descrição completa do projeto (objetivo, schema do item, fases, considerações legais) vive em [`CLAUDE.md`](CLAUDE.md). Este README cobre apenas instalação e uso.

## Pré-requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — gerenciador de pacotes e ambientes

Instalando o uv:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Instalação

```sh
uv sync                                # cria .venv e instala deps (incluindo grupo dev)
uv run playwright install chromium     # baixa o navegador para spiders JS
```

`uv sync` lê o `pyproject.toml`, resolve, e grava `uv.lock`. Para reproduzir o ambiente exato em outra máquina, comite o `uv.lock` e rode `uv sync --frozen`.

## Estrutura

| Pasta              | Conteúdo                                                            |
| ------------------ | ------------------------------------------------------------------- |
| `discovery/`       | Fase de descoberta e análise de sites (httpx + BeautifulSoup)       |
| `scrapy_project/`  | Projeto Scrapy com spiders dedicados por leiloeiro                  |
| `data/raw/`        | Saídas brutas dos spiders                                           |
| `data/intermediate/` | Artefatos das fases de descoberta (CSVs)                          |
| `data/processed/`  | Dataset final consolidado                                           |
| `reports/`         | Relatórios manuais (ex.: classificação dos sites)                   |

## Testes

```sh
uv run pytest
```

## Status

Esqueleto inicial. Nenhum spider implementado ainda — veja a tabela de fases em `CLAUDE.md`.
