# Fila de spiders a implementar — gerada 2026-05-14 21:55

Ordem por ROI (n° de leiloeiros high/medium descobertos).
Marcar `[x]` ao completar. Cada item commit isolado.

## Tier 1 — Providers SaaS (1 spider cobre múltiplos tenants)

- [x] **leiloes_judiciais_br** — 24 sites, 32 leiloeiros (32 high). Hosts ex: `mariafixerleiloes.com.br`, `capitalvalorleiloes.com.br`, `rioleiloes.com.br`. *2026-05-14: spider reescrito usando API JSON `/core/api/get-leiloes` + `/core/api/get-lotes`. Smoke 22 items.*
- [x] **leilao_br** — 14 sites, 20 leiloeiros (16 high). Subdomínios `*.leilao.br`. Hosts ex: `mercadoleiloes.com.br`, `jmleiloes.leilao.br`, `e-leiloeiro.leilao.br`. *2026-05-14: spider Laravel e-leiloes. Smoke test 16 items com min_bid+market_value.*
- [x] **sishp** — 2 sites, 9 leiloeiros (8 high). Hosts: `lancenoleilao.com.br`, `sfrazao.com.br`. *2026-05-14: 3 tenants (sfrazao/lancenoleilao/lancetotal). Smoke test 10+12 items.*
- [~] **palacio_dos_leiloes** — 1 site, 7 leiloeiros (7 high). `palaciodosleiloes.com.br`. *SKIP: recon confirma que catálogo público do site só tem Automóvel/Eletro/Maquinário, sem categoria Imóveis. Real-estate score foi inflado por PDFs antigos. Reavaliar trimestralmente.*
- [~] **sodre_santoro** — 1 site, 6 leiloeiros (6 high). `sodresantoro.com.br`. *SKIP: Nuxt SPA + Azion WAF + Elasticsearch passthrough API que exige cookie bootstrap. Generic Playwright já existente retorna 0 items. Recon de 2026-05-01 indicava 47 imóveis ativos; provider não publica encerrados. Necessita spider Playwright dedicado com bootstrap de sessão.*
- [x] **leiloesweb** — 3 sites, 3 leiloeiros (3 high). `leiloeslaraforster.com.br`, `bampileiloes.com.br`, `selectleiloes.com.br`. *2026-05-14: PHP server-side com ISO-8859-1. Smoke 16 items.*
- [~] **leiloesbr** — 6 sites, 6 leiloeiros (1 high). *SKIP: recon confirma que provider é arte/numismática/filatelia/colecionismo. real_estate_score foi falso positivo. Não é alvo do pipeline.*
- [x] **bomvalor** — 1 site `apabrfleiloes.com.br` (1 high). *Spider já existia; smoke test 16 items.*
- [x] **araujo_leiloes** — 1 site `andrearaujoleiloes.com.br` (1 high). *Spider já existia.*

## Tier 2 — Sites próprios com ≥3 leiloeiros

- [x] ricoleiloes.com.br (11 leiloeiros, 11 high). *Spider dedicado em proprio_html_specific. Site tem só 1 imóvel ativo agora (Bem Imóvel Urbano, Dourado/SP, R$3.5M); extraído OK.*
- [~] fernandoleiloeiro.com.br (6, 6 high). *SKIP: Cloudflare managed challenge bloqueia httpx/Playwright simples. Requer cloudflare-bypass ou conta autenticada.*
- [~] tripolonileiloes.com.br (5, 5 high). *SKIP: React SPA (id=root, bundle.js dinâmico) com API encapsulada em configStore.getApiUrl(). Requer recon Playwright + descobrir API base.*
- [x] destakleiloes.com.br (4, 4 high). *2026-05-15: spider `dg_platform` (subclass de degrau_publicidade) usando sitemap Facebook-listings. Smoke test 19 items com min_bid + market_value.*
- [x] grupolance.com.br (4, 4 high). *2026-05-14: smoke test 19 items, ~8 com min_bid + market, ~11 só market (lotes ainda não em praça aberta).*
- [x] nossoleilao.com.br (4, 4 high). *2026-05-14: mesma plataforma que rico. Subclass com home crawl. 2 items extraídos (catálogo majoritariamente sucata/ferramentas — apenas 2 imóveis ativos).*
- [x] cencin.com.br (3, 3 high). *2026-05-14: subclass de RicoLeiloesSpider. Smoke test 2 items com min_bid.*

## Tier 3 — Sites próprios com 2 leiloeiros (high)

- [x] amaralleiloes.com.br *(rico clone — 2 items)*
- [x] focoleiloes.com.br *(rico clone)*
- [~] thaisteixeiraleiloes.com.br *(SPA/sem lote links no HTML)*
- [x] upleilao.com.br *(2026-05-15: coberto por `dg_platform`, sitemap Facebook-listings)*
- [~] cpkleiloes.com.br *(Laravel sem lotes inline, provavelmente JS-rendered)*
- [~] d1lance.com.br *(301 redirect — não inspecionado)*
- [x] multipliqueleiloes.com.br *(2026-05-15: coberto por `dg_platform`)*
- [~] leiloaria.com.br *(React SPA, mesma toolchain que tripolonileiloes)*
- [x] lottileiloes.com.br *(rico clone)*
- [~] frazaoleiloes.com.br *(SPA ASP.NET — `/Auction/Index/{id}/{tab}` mas conteúdo dos lotes não está no HTML estático)*
- [~] conceitoleiloes.com.br *(rico clone — sem imóveis no catálogo no momento do smoke; spider em standby)*
- [~] desantileiloes.com.br *(rico clone — 0 leilões na home no smoke; spider em standby)*
- [x] vivaleiloes.com.br *(2026-05-15: coberto por `dg_platform`)*
- [~] hastapublica.com.br *(HTML estático apenas meta tags; conteúdo via AJAX)*

## Tier 4 — Sites próprios com 1 leiloeiro (high)

Atacar só se tempo permitir. ~30+ sites; listagem completa em
`data/intermediate/auctioneers_real_estate_v3.csv` filtro `confidence=high`.

### Spiders rico-clone batch (2026-05-14)

Adicionados em `_rico_clones2.py` após batch-recon que identificou
12+ sites usando a mesma plataforma Laravel/PHP do RicoLeiloes:

- [x] casamartillo.com.br (26 leiloeiros high!) — 1 item smoke
- [x] pimentelleiloes.com.br (2) — 6 items smoke
- [x] 3torresleiloes.com.br (2)
- [x] victordortaleiloes.com.br (2)
- [x] clicleiloes.com.br (4)
- [x] rjleiloes.com.br (4) — 6 items smoke
- [x] cargneluttileiloes.com.br (4) — spider OK, 0 items no smoke (sem imóveis ativos)
- [x] leiloesaguiar.com.br (3)
- [x] maraurzedoleilao.com.br (3)
- [x] lancese.com.br (3)
- [x] realizaleiloes.com.br (3)
- [x] patiorochaleiloes.com.br (3)
- [x] mullerleiloes.com.br (3) → renomeado mullerleiloes_rico para não conflitar com muller.py existente
- [x] ccjleiloes.com.br (3)
- [x] jgcargneluttileiloes.com.br (3)

Sites com plataforma "dg" (cobertos via sitemap Facebook-listings —
spider `dg_platform`, subclass de `degrau_publicidade`, 2026-05-15):

- [x] teza.com.br (4) — smoke 7+ items
- [x] silvaleiloes.com.br (3) — smoke 18 items
- [x] gfleiloes.com.br (8) — smoke 8 items min_bid+market
- [x] casareisleiloes.com.br (2) — smoke 14 items
- [x] inovaleilao.com.br (2) — smoke 110 items mapeados

Spider `dg_platform` cobre os 9 hosts via DG_DEFAULT_HOSTS. Roda com:
    scrapy crawl dg_platform                 # todos
    scrapy crawl dg_platform -a urls=...     # subset

## Skipped (baixo ROI ou complexidade alta)

- `proprio_html` (34 sites tag genérica, sem padrão comum — long tail)
- `wix` (3 sites, 0 high — genérico difícil de parsear)
- `softgt` (5 sites, 0 high)
- `desconhecido` (14 sites, 4 high — vale reclassificar antes via site_analyzer)

## Acordo de implementação

Para cada item:
1. Ler recon em `specs/_providers/<provider>/` ou `specs/<slug>/` se existir
2. Fetch homepage + 1 página de detalhe via `httpx` pra entender HTML
3. Implementar `scrapy_project/leilao_scraper/spiders/<name>.py` seguindo o
   padrão de spiders existentes (ver `discovery/juntas_scraper/jucepar.py`
   ou `scrapy_project/leilao_scraper/spiders/proprio_html_specific/portalzuk.py`)
4. Smoke test: rodar com `-s CLOSESPIDER_ITEMCOUNT=3` e validar 1+ item
   com `minimum_bid` ou `scheduled_at` populado
5. Se passa: commit `feat(spider): <name>` referenciando `SPIDER_QUEUE.md`
6. Se 3 falhas consecutivas: parar e logar em comentário

## Restrições

- NÃO tocar `pipelines_supabase.py`, `items.py`, `pipelines.py`, ou outros
  arquivos compartilhados — abrir issue se precisar.
- NÃO rodar spiders em produção (-o SUPABASE_DSN=). Smoke test só local
  com JsonLines export desabilitado se possível, ou aceitar persistência
  no DB (UPSERT idempotente).
- Não commitar spiders com bug óbvio (zero items extraídos).
- Site exige captcha/login → pula, marca como skip.
