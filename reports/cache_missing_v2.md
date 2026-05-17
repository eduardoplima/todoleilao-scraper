# Diagnóstico — `provider=cache_missing` em `site_providers_v2.csv`

## Resumo

Após rodar `site_analyzer` sobre `auctioneers_real_estate_v4.csv` (886 sites)
e `detect_providers` em cima de `site_analysis_v2.csv`, 90 rows caíram em
`provider=cache_missing` — `detect_providers` não encontrou HTML local.

## Causa raiz (única)

**`dominio` salvo SEM esquema `http(s)://`**. Em 89 dos 90 casos, o campo
`dominio` no `auctioneers_real_estate_v4.csv` veio como
`www.exemplo.com.br` (sem `https://`). httpx levanta
`UnsupportedProtocol` / `ValueError`; Playwright propaga `pw:Error`. Ambos
os fetches falham, `_write_cache()` em `discovery/site_analyzer.py:130`
nunca grava `.static.html` nem `.dynamic.html` (gravação é condicional ao
HTML não estar vazio). O `screenshot_path` no CSV fica `""` (linha 446 do
site_analyzer), e `detect_providers.html_paths_for()` retorna `(None, None)`.

O caso 90 (`http://uol.combr` — typo do feed INNLEI, slug vazio,
não-leiloeiro) falha por `httpx_connect:ConnectError` e fica inviável de
recuperar.

## Categorização

| bucket | qtd |
|---|---:|
| `both_fetches_failed` (dominio sem esquema) | 89 |
| `both_fetches_failed` (typo `uol.combr`) | 1 |
| **total** | **90** |

Nenhum row se enquadra em "HTML em disco mas screenshot_path aponta pra
path diferente" — o cache é coerente, o problema é upstream.

## Exemplos

```
slug=rodolfo-da-rosa-schontag  dom='www.leiloeiropublico.com.br'
  error=httpx=httpx:UnsupportedProtocol; pw=pw:Error  screenshot_path=<empty>
slug=<empty>                   dom='www.realizaleiloes.com.br'
  error=httpx=httpx:UnsupportedProtocol; pw=pw:Error  screenshot_path=<empty>
slug=<empty>                   dom='WWW.LEITELEILOES.COM.BR'
  error=httpx=httpx:ValueError; pw=pw:Error  screenshot_path=<empty>
slug=<empty>                   dom='http://uol.combr'   (typo, não é leiloeiro)
  error=httpx=httpx_connect:ConnectError; pw=pw:Error
```

## Onde corrigir definitivamente (não feito aqui)

`discovery/site_analyzer.py:_httpx_fetch` deveria normalizar `url`
prependando `https://` se faltar esquema (e fallback para `http://` em
`SSLError`). O Playwright herda a mesma normalização. Sem alterar produção
agora — fix aplicado por script utilitário `scripts/repatch_cache_missing.py`
que regrava as 89 linhas + cache de HTML (ver `scripts/repatch_cache_missing.py`).
