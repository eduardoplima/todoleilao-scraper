# Batch C — Cobertura `proprio_html` (top 32 por real_estate_score)

Smoke test do spider genérico `proprio_html` rodado contra os 32 hosts em
`data/intermediate/spider_gap_batch_c_proprio_html.csv`. Comando:

```bash
uv run scrapy crawl proprio_html \
  -a urls=<host> -a incremental_only=false \
  -s CLOSESPIDER_ITEMCOUNT=5 -s LOG_LEVEL=INFO \
  -s ROBOTSTXT_OBEY=False -s CLOSESPIDER_TIMEOUT=45 \
  -s HTTPCACHE_ENABLED=False
```

Critério OK: ≥3 lotes com `minimum_bid` + `title` + `source_url`.

## Resumo

| Status | Qtd | Descrição |
|---|---|---|
| OK | 2 | Smoke do genérico produziu ≥3 lotes com campos críticos preenchidos |
| PARCIAL | 3 | Lotes emitidos mas <3 com `minimum_bid` ou todos dropados pelo filtro `_detail_is_imovel` |
| FAIL / requires_recon | 27 | Zero lotes extraídos — padrões de URL não casam ou SPA não renderiza a tempo |

Nenhum spider custom (`proprio_html_specific/<slug>.py`) foi criado: dos 3 PARCIAL,
todos têm falha na *descoberta* (pouca URL casa o regex ou conteúdo filtrado como
não-imóvel), não na *extração* — o hook `_fixup_item` roda só após `parse_property`
emitir item, então não conserta esses casos. Marquei-os como `requires_recon`.

## Tabela completa

| slug | host | status | spider_custom_created | observações |
|---|---|---|---|---|
| frazaoleiloes | www.frazaoleiloes.com.br | OK | não | 7 lotes; todos com `minimum_bid`. `market_value=None` porque a página renderizada não expõe "Avaliação" no body text — apenas lance mínimo. Genérico OK. |
| leje | www.leje.com.br | requires_recon | não | SPA jQuery; home não expõe links de lote, fallback paths `/leiloes /lotes /categoria/imoveis /imoveis` retornam 0. Listings reais usam `?acao=evento&cod=<id>` (não casa regex). |
| posseimoveis | posseimoveis.com.br | requires_recon | não | Home sem lote-links; `/imoveis` 404. Site é landing-only (dynamic). |
| inovaleilao | www.inovaleilao.com.br | requires_recon | não | Lotes em `/subcategorias/lotes/<slug>` — não casa nenhum dos `_LOT_PATH_PATTERNS`. |
| valland | www.valland.com.br | PARCIAL → requires_recon | não | Home revelou 1 lote (`/lote/<id>/<slug>` — site é white-label de hastapublica.com.br). Único lote extraído com `min_bid` OK, mas <3 → não atende threshold. |
| hastapublica | hastapublica.com.br | requires_recon | não | hastapublica.com.br redireciona para hastapublica.lel.br (provider `leilao_pro` segundo `site_providers.csv`). Não é mais custom. |
| loteleiloes | www.loteleiloes.com.br | requires_recon | não | Home sem links de lote; fallback paths 0. |
| d1lance | d1lance.com.br | requires_recon | não | Idem. |
| turanileiloes | www.turanileiloes.com.br | requires_recon | não | Listing real é `/imoveis` que linka para `/auditorio/<slug>` (página de leilão) — não para lotes diretamente. Pattern miss. |
| rossileiloes | rossileiloes.com.br | requires_recon | não | Usa `/lote/detalhe/<id>` — regex `/lote[s]?/\d+` exige `\d+` logo após `/lote/`. Pattern miss. |
| rochaleiloes | rochaleiloes.com.br | PARCIAL → requires_recon | não | Home expôs 13 lote-URLs mas TODAS foram dropadas por `_detail_is_imovel=False` (Vue SPA — `<title>` SSR genérico, h1/og:title vazio antes da hidratação). `_fixup_item` não conserta isso (filtro roda antes). |
| maleiloesro | www.maleiloesro.com.br | requires_recon | não | Site só lista pregões CONAB (commodities agrícolas), não imóveis. Filtro corretamente dropou 4 lotes. Não há imóvel para extrair — recon não vai ajudar; precisa exclusão. |
| arnaldoleiloes | arnaldoleiloes.com.br | requires_recon | não | URLs `/lote/<slug>/<id>/` (slug intermediário) — não casa regex. |
| leiloesbrasil | www.leiloesbrasil.com.br | requires_recon | não | SPA dynamic; fallback /imoveis 0. |
| leiloeiropublico | www.leiloeiropublico.com.br | requires_recon | não | 4× 404 em todos os fallback paths. |
| lancecertoleiloes | www.lancecertoleiloes.com.br | requires_recon | não | Lotes em `/leilao/<slug>/lote/<id>` — regex `/leilao/\d+/lote/\d+` exige `\d+` no slug do leilão (e.g. `050526PART` não casa). |
| mcleilao | www.mcleilao.com.br | requires_recon | não | SPA com routing `#/home`; fallbacks 0. |
| daux | www.daux.com.br | requires_recon | não | Home sem lote-links; listing real é `/leilao/<id>` → drill-down necessário. |
| sancarleiloes | www.sancarleiloes.com.br | requires_recon | não | curl 403 (AWS ELB); Playwright passa mas /imoveis 0. |
| dearaujoleiloes | dearaujoleiloes.com.br | requires_recon | não | Links de leilão em `/externo/leilao/<id>/<slug>` (não de lote direto). Pattern miss. |
| formulaleiloes | www.formulaleiloes.com.br | requires_recon | não | URLs `?pg=item&id=<n>` — regex de query string só aceita `?cod=` / `?id=` como primeiro parâmetro. `&id=` não casa. |
| lmleiloes | www.lmleiloes.com.br | requires_recon | não | curl 403; /imoveis 0. |
| caiapoleiloes | www.caiapoleiloes.com.br | OK | não | 14 lotes extraídos. Apenas 3 com `minimum_bid` (lotes pré-abertura mostram só "Valor Avaliação"). Mistura veículos+imóveis, mas atende threshold. |
| ubaldoleiloes | www.ubaldoleiloes.com.br | requires_recon | não | /imoveis 0. |
| lanceja | www.lanceja.com.br | PARCIAL → requires_recon | não | 1 lote extraído (R$ 47M imóvel São Paulo), <3 threshold. URLs `/lotes/<slug>` — regex casa `/lotes/\d+` mas slug usa `<num>-<slug-texto>`. Casa por sorte para alguns. |
| teleselimaleiloes | www.teleselimaleiloes.com.br | requires_recon | não | curl 403; /imoveis 0. |
| leiloesdonorte | www.leiloesdonorte.com.br | requires_recon | não | Fallbacks 0. |
| leiloesbrasilto | leiloesbrasilto.com.br | requires_recon | não | Fallbacks 0. |
| portaldoleiloeiro | www.portaldoleiloeiro.com.br | requires_recon | não | Template "grupo auction brazil" — `?pg=item&id=` (mesma issue de formulaleiloes). |
| mirandacarvalholeiloes | www.mirandacarvalholeiloes.com.br | requires_recon | não | Home aponta para `/lotes-abertos-para-lance` (não casa pattern); /imoveis 0. |
| leilo | leilo.com.br | requires_recon | não | Vue SPA pesado; mesmo com Playwright, fallbacks /lotes /categoria/imoveis /imoveis /leiloes todos retornaram 0. |
| leiloesbrasilcassiano | leiloesbrasilcassiano.com.br | requires_recon | não | Fallbacks 0. |

## site_providers.csv

Adicionados 2 rows com `provider=proprio_html, confianca=auto`:

```
,CARLOS EDUARDO LUIS CAMPOS FRAZAO,https://www.frazaoleiloes.com.br/,proprio_html,auto,smoke=batch_c; 7lots; minbid_ok,dynamic
,Rossana Paiva Borges De Oliveira,https://www.caiapoleiloes.com.br/,proprio_html,auto,smoke=batch_c; 14lots; minbid=3/14; veiculos_mixed,static
```

Os demais 30 hosts ficam sem entrada `confianca=auto` (preservam a classificação
prévia de `confianca=low` ou ausência de row, conforme o caso). Recomendo
`requires_recon` para todos eles no próximo ciclo.

## Padrões observados (gotchas)

1. **URL patterns não casam o regex genérico** (causa dominante de FAIL):
   - `/lote/detalhe/<id>` (rossileiloes)
   - `/subcategorias/lotes/<slug>` (inovaleilao)
   - `?pg=item&id=<n>` — `&id=` em vez de `?id=` (formulaleiloes, portaldoleiloeiro)
   - `/leilao/<slug-alfanumerico>/lote/<id>` — slug não-numérico (lancecertoleiloes)
   - `/externo/leilao/<id>/<slug>` (dearaujoleiloes)
   - `/lote/<slug>/<id>/` (arnaldoleiloes)
   - `?acao=evento&cod=<id>` (leje)

   Sugestão: ampliar `_LOT_PATH_PATTERNS` no genérico ou criar novo enum
   "padrão_X" + classificador prévio.

2. **SPAs com hidratação tardia**: Vue/Angular sites onde o `<title>` SSR é
   genérico e `og:title`/`h1` só populam após JS. O check `_detail_is_imovel`
   roda no momento que `parse_property` recebe o response — se Playwright
   não esperou hidratação suficiente, o lote é dropado mesmo sendo imóvel
   (rochaleiloes, leilo). `PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT` é 45s mas
   `wait_until` é `load`, não `networkidle`.

3. **AWS ELB 403 para curl** (sancarleiloes, lmleiloes, teleselimaleiloes,
   caiapoleiloes): Playwright passa pelos challenges. Não bloqueia o spider,
   só dificulta investigação manual.

4. **Sites sem imóveis na vitrine atual** (maleiloesro = CONAB commodities).
   Spider funcionou corretamente — filtro `_detail_is_imovel` dropou tudo.
   Não é caso de recon; é caso de exclusão do escopo "real estate".

5. **White-label oculto** (valland → hastapublica.com.br): valland.com.br
   serve URLs de lote do CDN/template de hastapublica.com.br, sugerindo
   serem o mesmo backend. Esse já é classificado como `leilao_pro` no
   `site_providers.csv` (via hastapublica.lel.br). Vale checar se valland
   também é leilao_pro disfarçado.

6. **Pré-abertura mostra só "Avaliação"** (caiapoleiloes): lotes ainda não
   abertos exibem `Valor Avaliação: R$ X` mas não `Lance Mínimo`. O genérico
   captura `market_value=X` e `minimum_bid=None`. Pode aumentar fill rate
   se o fallback "se min_bid==None, copia market_value" for adicionado —
   mas isso é decisão de schema, não de spider.
