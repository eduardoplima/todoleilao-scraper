# Issues pendentes detectados — 2026-05-14

Lista compilada do trabalho desta sessão. Ordem por prioridade de impacto.

---

## 🔴 NOVO 2026-05-14 (agente noturno)

### LJB — leiloes_judiciais_br RESOLVIDO 2026-05-14
Spider reescrito usando API JSON `/core/api/get-leiloes` + POST
`/core/api/get-lotes` (descobertos no JS bundle `container.js`).
Smoke 22 items. Padrão funciona em todos os tenants do cluster
(32 leiloeiros high cobertos).

### Plataformas "dg" e "Next/React" — SPA-heavy bloqueadas
Identificada uma família grande de sites usando o mesmo template
"dg-lote-titulo" + `<span class="ValorMinimoLancePrimeiraPraca">`
(preços/datas renderizados client-side via jQuery templates +
WebSocket/AJAX). HTML estático tem só título, ID, imagens —
preços vêm vazios. Lista parcial:

- destakleiloes.com.br (4 high)
- gfleiloes.com.br (8 high)
- vivaleiloes.com.br (2 high)
- multipliqueleiloes.com.br (2 high)
- teza.com.br (4 high)
- silvaleiloes.com.br (3 high)
- upleilao.com.br (2 high)
- casareisleiloes.com.br (2 high)
- inovaleilao.com.br (2 high)

Total ~30 leiloeiros high bloqueados. **Resolução**: spider Playwright
único que renderiza a página, espera o XHR resolver e extrai os
valores `dg-lote-titulo` + `ValorMinimoLance*`. Investimento ~3h.

### Cloudflare Managed Challenge
- fernandoleiloeiro.com.br (6 high) — bloqueia tudo
- vipleiloes.com.br (12 high!) — maior site bloqueado por CF

### Next.js / React SSR
- simonleiloes.com.br (2 high) — Next.js streaming RSC
- tripolonileiloes.com.br (5 high) — React SPA
- balbinoleiloes.com.br (5 high) — React SPA
- leilo.com.br (8 high) — Vue SPA, 110+ chunks

### Sodre Santoro
Nuxt SPA + Azion WAF + Elasticsearch passthrough. prd-api existe mas
imóveis ainda exigem bootstrap de sessão. ~6 leiloeiros high, todos
da mesma família.

---

## 🔴 Alta — disparando em prod ou bloqueando feature

### 1. Cap de 2000 rows nos helpers do frontend
Hoje o front roda agregação em memória após `.limit(2000)` em `lib/supabase.ts`. **Já está disparando**: RJ tem 10.276 abertos, GO 4.787, SP 2.070 — front renderiza contagens silenciosamente erradas.

- **Trabalho no scraper**: ✅ feito (arquivos prontos, falta aplicar)
  - `sql/public_v1_stats_mv.sql` cria `public_v1.uf_stats` (1 row/UF) e `public_v1.municipality_stats` (1 row/UF+município) — cobre `getUfStats`, `getMunicipalityStats`, `getMunicipalitiesByUf`, `getDistrictsByMunicipality`.
  - `sql/public_v1_refresh.sql` atualizado pra incluir o refresh agendado das 2 MVs no `pg_cron`.
- **Aplicar**:
  ```bash
  psql "$SUPABASE_DB_URL" -f sql/public_v1_stats_mv.sql
  psql "$SUPABASE_DB_URL" -f sql/public_v1_refresh.sql
  ```
- **Trabalho no frontend**: trocar os 4 helpers pra `SELECT * FROM public_v1.uf_stats|municipality_stats`.

### 2. Geom — voltou a 76% sem geom após crawl Caixa
Ondas 1+3 reduziram de 92% → 36% sem geom, mas o Caixa adicionou +18k lots desde então. Estado atual: **21.696/28.641 (76%) sem geom**.

Fix (não-destrutivo, idempotente):
```bash
psql "$SUPABASE_DB_URL" -c "
  UPDATE core.address a SET
    geom = m.centroid,
    geocoding_source = 'municipality_centroid',
    geocoding_confidence = 0.1
  FROM core.municipality m
  WHERE a.municipality_code = m.ibge_code AND a.geom IS NULL;
"
uv run python scripts/geocode_addresses.py --limit 30000 --rate 1.0
psql "$SUPABASE_DB_URL" -c "REFRESH MATERIALIZED VIEW CONCURRENTLY public_v1.lot_search;"
```

Rodar **depois** do Caixa terminar pra evitar refazer trabalho. ETA Caixa: ~1-3h (resta Norte).

Solução definitiva: incluir Nominatim como cron pós-spider (não implementado).

### 3. Soleon — 267 lots ativos sem `auction_round` *(parcialmente revisado em 2026-05-14)*
Re-rodagem executada nesta sessão revelou **dois problemas distintos**:

**3a. Cassiano (`BidderLancePlatformSpider`) nunca extraiu datas.**
Spider herda de `_bidder_lance_platform.py` que não tem regex de `first_auction_date` / `second_auction_date` / `auction_phase`. Items raspados só têm `address, auctioneer, description, images, minimum_bid, property_type, scraped_at, source_listing_url, title, url`. Pipeline `_insert_round` exige `scheduled_at + minimum_bid` → 0 rounds.

**Trabalho**: adicionar parsing de datas em `_bidder_lance_platform.py`. Inspecionar HTML real de cassianoleiloes.com.br pra identificar onde a data aparece (Müller e Rech herdam da mesma classe e provavelmente sofrem do mesmo gap — verificar contagens via DB).

**3b. Soleon (Ferreira/Purcena) — fix anterior cobre só ~5-10% dos lots.**
Re-rodagem em 2026-05-14: ganho de apenas **+2 rounds** (Purcena 7→9). Ferreira inalterado em 19 c/round de 172 ativos. Log mostra que a maioria dos leilões devolve `event=soleon_leilao_dates first=None second=None` — o template `<h6>Data 1º Leilão: ...</h6>` que o fix do "Agente 2" cobre não existe em ~90% dos lots.

**Trabalho**: revisitar parser. Inspecionar HTML de `/leilao/<id>/lotes` em ferreira/purcena pra ver formatos alternativos (data dentro de `info-adicional`, JSON inline, dataLayer, etc).

### Bug grave detectado e corrigido nesta sessão (commit `1ff2f14`)
O commit `9ddb010` (do dia 2026-05-13) introduziu `_insert_address` com bloco geom em sub-SELECT e CASE que falhava com `could not determine data type of parameter $10` quando `muni_code=None`. Estava silenciosamente abortando items de TODO spider que insere endereço sem município resolvido. Corrigido com cast `%s::text`. Caixa em curso (PID 13563) não foi afetado pois carregou o módulo antigo em memória. **Spiders novos que rodaram entre 9ddb010 e 1ff2f14 podem ter perdido inserts** — vale validar contagens dos spiders rodados nesse intervalo.

---

## 🟡 Média — degrada qualidade mas não bloqueia

### 4. Crawl Caixa — 6 UFs do Norte pendentes
AM, AC, RR, AP, TO, RN ainda não foram processadas. Spider ativo (PID 13563) deve completar em 1-3h.

Após terminar, MG aparece como anomalia que voltei a ver hoje: passou de "pulado" pra **1.090 lots**. Mas pode estar incompleto (cidades antigas faltando). Validar contra IBGE de SP/GO (que têm muito mais lots) — se MG ficar muito abaixo do esperado, re-rodar com `caixa -a estados=MG -a auto_cidades=true`.

PB tem só **2 lots** — vestígio de run anterior; precisa re-rodar.

### 5. mega_leiloes — 218 lots ativos sem UF
Spider tem regex correta (`/imoveis/<tipo>/<uf>/<cidade>/`), mas 218 lots antigos foram raspados antes do parser. UPSERT idempotente cobre:
```bash
scrapy crawl mega_leiloes
```

### 6. albertomacedo — re-rodar para popular UF dos 245 lots
Fix do `s4b_digital.py` foi commitado nesta sessão (commit `9ddb010`) — fallback URL→UF. Falta re-rodar:
```bash
scrapy crawl s4b_digital -a sites=albertomacedoleiloes.com.br
```

### 7. leilaobrasil — 187 lots sem UF, parser não implementado
Slug `/eventos/leilao/casa-em-avare-com-160-70-m/lote/11961/...` não contém UF. Description é curta ("Casa em Avaré com 160,70 m²"). Spider `suporte_leiloes.py` já tem extração de bloco "Localização" mas não casa para esses lots.

Trabalho: inspecionar HTML de um lot real do leilaobrasil, achar onde a UF aparece (breadcrumb? footer?) e adicionar parser específico no `suporte_leiloes.py`.

### 8. JUCERR — única junta ainda stub
Site `https://jucerr.rr.gov.br/leiloeiros/` existe (200 OK) mas só publica manuais PDF (matrícula/afastamento/cancelamento), sem lista nominal. Estimativa: 5-7 leiloeiros (RR é estado pequeno).

Resolução: pedido via **LAI** (Lei de Acesso à Informação). 1 vez/ano cobre.

### Resolvido em 2026-05-14 (parcial): inferência de domínio via email

`discovery/infer_domains_from_email.py` adicionado. Roda em ~1s, popula
`dominio = http://{host}` para leiloeiros sem `dominio` mas com email
não-genérico. Blacklist: gmail/hotmail/yahoo/uol/innlei.org.br/etc.

Pipeline encadeado: infer → enrich_auctioneers --no-cache → filter_real_estate.

| | antes | depois | Δ |
|---|---:|---:|---:|
| high | 409 | 560 | +151 |
| medium | 160 | 214 | +54 |
| **total imobiliário** | **569** | **774** | **+205 (+36%)** |

Caso testado: Marcus Dantas Nepomuceno (RN) — INNLEI tinha email
`marcusnepomuceno@mnleilao.com.br` mas campo `dominio` vazio. Agora
classificado como `medium` com score 4.9 (site MN Leilão real, com
leilões TJRN/TRT/PRF).

### Bug menor pendente — enrich_auctioneers parser

4+ sites RN (leiloesrn.com.br, erickleiloes.com.br,
robertofernandesleiloes.com, atlanticoleiloes.com.br) caem em
`site_error=other:ValueError` no parser BeautifulSoup. Possivelmente
XMLParsedAsHTMLWarning escalando em alguns charsets. Fix: passar
`features="xml"` quando content é XML, ou tratar `ValueError`
especificamente. Baixo impacto (~5-10 sites no total).

### 9. Enrichment dos 264 leiloeiros junta_only sem site
264 dos 339 `junta_only` cairam em `confidence=unknown` no `filter_real_estate.py` porque não têm `site_*` data (não estão no INNLEI). Pra descobrir os de imóveis nesse grupo:

- **Curto prazo**: alguns scrapers de junta já capturam endereço/telefone/email (JUCEB, JUCEPA, JUCEAL). Re-rodar com schema expandido (`nome,matricula,junta_sigla,uf,situacao,juc_url,email,telefone,site,endereco,scraped_at`) e re-enriquecer.
- **Médio prazo**: Google search "nome+leiloeiro+UF" pra cada um → encontrar domínio próprio.

Hoje: 685 leiloeiros classificados como imóveis (502 high + 183 medium). Estimativa pós-enrichment: +50-100.

---

## 🟢 Baixa — manutenção / refinamento

### 10. JUCESP — PDF de 2023 desatualizado
`https://www.institucional.jucesp.sp.gov.br/downloads/Relacao_de_Leiloeiros.pdf` é snapshot do DOE de 2023, cobre matrículas ~960-1389. Quando JUCESP republicar, atualizar `LISTING_URL` em `discovery/juntas_scraper/jucesp.py`. Provavelmente perde leiloeiros pré-2015 e pós-2023.

### 11. JUCEMA — PDF de 2021
`http://api.jucema.ma.gov.br/files/1626201361_Leioleiros%202021.2.pdf` (typo "Leioleiros" é original do servidor). Pode estar desatualizado. Validar contra portal JUCEMA atual.

### 12. Deduplicação multi-junta
317 leiloeiros aparecem em ≥2 juntas (cruzando por nome normalizado). Casos extremos: `Daniel Elias Garcia` em 24 juntas, `Alex Willian Hoppe` em 20. Não está claro se é homônimo ou matrícula multi-estado. Resolução exige CPF (não capturado pela maioria das juntas) — fica como TODO de longo prazo.

### 13. JUCEPA — 1 nome truncado
Lot 1/67 do JUCEPA tem nome partido pelo HTML em 3 linhas. Parser pega `RIBEIRO DOS SANTOS` em vez de `EDIVAN RIBEIRO DOS SANTOS`. Heurística específica quebraria outros casos. 98.5% de acerto é aceitável.

### 14. Sitemap próximo do limite (issue irmã do cap-2000)
`app/sitemap.ts` tem `.limit(45000)`. Google limita a 50k URLs/sitemap. Com 28k lots ativos hoje + 27 UFs + ~2k municípios + estáticas = ~31k. Aguenta — particionar antes dos 40k.

### 15. Pipeline geocoder pós-spider (automação)
Hoje o `scripts/geocode_addresses.py` roda manualmente. Quando muitos lots novos entram (ex.: Caixa), gap volta. Cron Fly machine (1×/dia) resolve.

### 16. Caixa modo `refazer_sem_data` ainda perde UF em alguns casos
225 lots Caixa ativos sem UF — caem em casos onde `_ADDRESS_FULL_RE` não casa e `_NOME_TO_UF.get(group(7))` retorna None. Cobertura média 93% já é aceitável.

---

## Arquivos referência

- `sql/public_v1_stats_mv.sql` — DDL pronto pras 2 mat views
- `sql/public_v1_refresh.sql` — atualizado pra refrescar uf_stats + municipality_stats
- `scrapy_project/leilao_scraper/pipelines_supabase.py:438` — `_insert_address` corrigido (centroide no INSERT)
- `scrapy_project/leilao_scraper/spiders/s4b_digital.py:330` — fallback URL→UF
- `scrapy_project/leilao_scraper/spiders/caixa.py:762` — fallback group(7) → `_NOME_TO_UF`
- `discovery/juntas_scraper/` — 26/27 juntas implementadas (só JUCERR pendente)
- `data/intermediate/auctioneers_unified.csv` — 3.088 leiloeiros (INNLEI + Juntas)
- `data/intermediate/auctioneers_real_estate_v2.csv` — 685 classificados como imóveis (502 high + 183 medium)
