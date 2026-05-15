# Fila de spiders a implementar — gerada 2026-05-14 21:55

Ordem por ROI (n° de leiloeiros high/medium descobertos).
Marcar `[x]` ao completar. Cada item commit isolado.

## Tier 1 — Providers SaaS (1 spider cobre múltiplos tenants)

- [ ] **leiloes_judiciais_br** — 24 sites, 32 leiloeiros (32 high). Hosts ex: `mariafixerleiloes.com.br`, `capitalvalorleiloes.com.br`, `rioleiloes.com.br`. Recon em `specs/_providers/leiloes_judiciais_br/` se existir. *2026-05-14: spider existente quebrado (path `/imoveis` mudou para `/leilao/index/imoveis` + Vue SPA dinâmico). Ver ISSUES_TODO.md.*
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
- [ ] fernandoleiloeiro.com.br (6, 6 high)
- [ ] tripolonileiloes.com.br (5, 5 high)
- [ ] destakleiloes.com.br (4, 4 high)
- [ ] grupolance.com.br (4, 4 high)
- [ ] nossoleilao.com.br (4, 4 high)
- [ ] cencin.com.br (3, 3 high)

## Tier 3 — Sites próprios com 2 leiloeiros (high)

- [ ] amaralleiloes.com.br
- [ ] focoleiloes.com.br
- [ ] thaisteixeiraleiloes.com.br
- [ ] upleilao.com.br
- [ ] cpkleiloes.com.br
- [ ] d1lance.com.br
- [ ] multipliqueleiloes.com.br
- [ ] leiloaria.com.br
- [ ] lottileiloes.com.br
- [ ] frazaoleiloes.com.br
- [ ] conceitoleiloes.com.br
- [ ] desantileiloes.com.br
- [ ] vivaleiloes.com.br
- [ ] hastapublica.com.br

## Tier 4 — Sites próprios com 1 leiloeiro (high)

Atacar só se tempo permitir. ~30+ sites; listagem completa em
`data/intermediate/auctioneers_real_estate_v3.csv` filtro `confidence=high`.

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
