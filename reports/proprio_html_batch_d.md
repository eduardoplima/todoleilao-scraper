# Batch D — proprio_html spider gap (32 leiloeiros)

Sprint Sprint 4 fatia D. Smoke do `ProprioHtmlSpider` genérico em 32 leiloeiros
remanescentes do gap `proprio_html` (próximos 32 após batch C), do
`data/intermediate/spider_gap_batch_d_proprio_html.csv`.

Metodologia: para cada host, `scrapy crawl proprio_html -a urls=<home>
-s CLOSESPIDER_ITEMCOUNT=5` com timeout 30s (cache HTTP habilitado).
Resultado classificado em:

- **ok** ≥3 lotes completos → append row `provider=proprio_html` em
  `site_providers.csv`.
- **partial** → spider-específico em `proprio_html_specific/<slug>.py`
  + fixtures + testes.
- **recon** → 0 lotes (ou só falsos positivos) → marcar `requires_recon`,
  sem spider.

Status final batch D:

| slug | host | status | spider_custom_created | observações |
|------|------|--------|-----------------------|-------------|
| wrleiloes | wrleiloes.com.br | recon | não | home só lista `/leilao/{id}` (índice de leilões); precisa drill-down 2 níveis pra chegar nos `/lote/{id}`. JS-heavy carousel. |
| andre-mario-araujo | andrearaujoleiloes.com.br | covered | não | site_providers já tem este host mapeado para `araujo_leiloes` (agent prévio). batch_d skip. |
| eduardo-gomes | leiloeiroeduardo.com.br | recon | não | home estática mas sem links `/lote/` — SaaS provavelmente leilo.com.br/portal externo. |
| claudio-sousa-dos-santos | allianceleiloes.com.br | recon | não | home produz 0 links que casem padrões; fallback `/imoveis`, `/lotes`, `/categoria/imoveis` retornam 0. Site é SPA / categorias dinâmicas. |
| aline-marques | alinemarquesleiloeira.lel.br | recon | não | template "AlineMarques/PauloBotelho/LeiloeiroPúblico" — URLs `/leiloes/{slug}/{id}` NÃO casam o regex `/leilao/\d+/lote/\d+` do genérico. Requer pattern adicional + custom-extract (escopo maior). |
| james-arthur-lobo-lisboa | leilaodearte.com | recon | não | Site sem href hits — provavelmente página parking / migrado para iarremate. |
| claudio-cesar-kuss | claudiokussleiloes.com.br | recon | não | Leiloeiro de veículos (não imóveis); usa `javascript:openWindow(...)` para detalhe — sem URLs estáticas. |
| jorge-luiz-molgado | molgado.com.br | recon | não | home só `/lotes/?cate[]=N` (query-paginate por categoria, não link de lote individual). |
| vicente-de-paulo-cota | vipleiloes.com.br | recon | não | home retorna 200 mas sem links de lote individuais; fallback paths todos 200 mas 0 lots. SPA com hash routing. |
| osman-sobral | leiloesfreire.com.br | recon | não | Detalhes em `/leilao/lote/{N}` mas template Vue (`{{lote.nome}}` placeholder); og:title e h1 só com nome do site. Mesma classe do schulmann mas Vue não hidrata → não dá pra fixar sem refazer extração. |
| adriano-de-souza-cardoso | capitalleiloes.com.br | recon | não | home retorna 200, 0 lotes detectados pelo genérico. SPA. |
| jeferson-benedetto | benedettoleiloes.com.br | recon | não | home 200, 0 lotes; render hybrid mas conteúdo via XHR. |
| fabio-maciel-amarante | nortedeminasleiloes.com.br | recon | não | home tem `/leilao/{N}` (índice), sem `/lote` direto; mesmo gap que wrleiloes. |
| cristiano-branchieri-escola | cristianoescolaleiloes.com.br | recon | não | home tem `/lotes` e `/lotes?modalidade%5B%5D=4` mas listagem dinâmica; 0 lotes pelo genérico. |
| leonardo-schulmann | schulmannleiloes.com.br | **partial → custom** | **schulmann_leiloes.py** | Generic encontrou 51+ URLs `detalhe.php?id=N&imovel=…` mas dropava 100% como non_imovel: dois `<h1>` (primeiro é `Menu principal` a11y, segundo é o real `h1#featured-heading`); sem `og:title`; texto "IMÓVEL" só aparece após char 8700, fora do cap `[:3000]` do genérico. **Custom emite 47 imóveis com `title`, `minimum_bid`, `market_value` corretos. Veículos (Semirreboque) são filtrados via veto título.** |
| bruno-lopes-pereira-dos-reis | iarremate.com | recon | não | É portal de arte (`Bruno Reis Escritório de Arte`), não imóveis. Provider real é iarremate (catálogo arte/antiguidade). |
| ioneide-maria-fernandes-sampaio | almoedaleiloes.com.br | recon | não | URL `/externo/leilao/{N}/{slug}` — pattern não bate com genérico. |
| flavio-bittencourt-garcia | flaviogarcia.lel.br | recon | não | home 200, 0 lotes. Possível site parado. |
| luiz-odair-favareto | favaretoleiloes.com.br | recon | não | home 200, 0 lotes; sem links de lote estáticos. |
| adilson-guimaraes-araujo | aguialeiloes.com.br | recon | não | path `/externo/` retorna 0 lotes; mesmo template `almoedaleiloes`. |
| alexsandro-pereira | alexsandroleiloes.com.br | recon | não | home 200, 0 lotes; SPA. |
| braulio-ferreira-neto | braunaleiloes.blogspot.com | recon | não | Blogspot — sem padrão de lote estático. |
| paulo-roberto-nakakogue | vardanaleiloes.com.br | recon | não | path `/vardana/` (sub-tenant) — 0 lotes; SPA. |
| elisa-brunken-da-silva | sindileisc.com.br | recon | não | sindicato de leiloeiros SC, não leilão direto. |
| paulo-augusto-botelho | paulobotelholeiloeiro.com.br | recon | não | mesmo template `AlineMarques` — URL `/leiloes/{slug}/{id}` não casa regex. |
| fernando-albuquerque-lins | albuquerquelins.com.br | recon | não | home 200, 0 lotes. |
| cristiane-borguetti | lopesleiloes.com.br | recon | não | home 200, 0 lotes; SPA. |
| marcelo-camargo-de-brito | camargonet.com | recon | não | site genérico/blog; sem padrão de lote. |
| gease-henrique-oliveira-miguel | oliveiramiguel.adv.br | recon | não | É site de escritório de advocacia, não leiloeiro. Genérico emitiu 9 "items" mas todos eram páginas `/area.aspx?id=N` (áreas de atuação) — **falsos positivos**, descartar. |
| joao-paulo-ferreira (montenegro2) | montenegroleiloes.com.br | recon | não | duplicate slug — site já em batch anterior; 0 lotes. |
| antonio-jose-silva-filho | ajleiloes.com.br | recon | não | rendering=dynamic, requires_js — genérico não chega nos lotes. |
| elenice-lira-sales | hugedomains.com | recon | não | domínio parqueado pela HugeDomains — não é o site do leiloeiro. Site original (`leiloesbrasil.com`) está à venda. |

## Resumo numérico

- 32 hosts no batch D
- 1 host com spider custom criado (**schulmann_leiloes** — 47 imóveis)
- 1 host já coberto por batch anterior (andrearaujoleiloes → araujo_leiloes)
- 30 hosts marcados `requires_recon` (entrada para Sprint 5 / recon manual)

## Causas raiz dominantes (30 recon)

1. **JS/SPA renderiza listagem via XHR** (≈ 14 hosts): genérico vê apenas
   carcaça HTML; fallback paths retornam 200 mas sem links.
2. **Template usa pattern `/leiloes/{slug}/{id}` ou `/leilao/{id}`**
   (índice de leilões, não lotes) (≈ 6 hosts): AlineMarques, PauloBotelho,
   wrleiloes, nortedeminas, leiloesfreire, almoeda.
3. **Não-leiloeiro** (≈ 6 hosts): sites de advogado, escritório de arte,
   sindicato, domínio parqueado, blog — listagem original errada.
4. **Vue/Angular sem hidratação no Playwright** (≈ 3 hosts):
   leiloesfreire, cristianoescola, schulmann (lots viáveis, mas títulos via
   `{{lote.nome}}` placeholders).
5. **JS-only auction window** (1 host): claudiokuss usa
   `javascript:openWindow()` para detalhes.

## Spider criado

### `schulmann_leiloes` (`proprio_html_specific/schulmann_leiloes.py`)

- Override de `parse_property` (e não de `_fixup_item`) — precisava
  alterar o filtro `_detail_is_imovel` ANTES do `loader.load_item()`.
- Estratégia: pega `h1#featured-heading` (skip o `h1.assistive-text`),
  usa título + url_slug + anchor `IMÓVEL:` no body para decidir se
  é imóvel; veto absoluto para títulos contendo veículo (Semirreboque,
  Caminhão, etc.).
- Pre-extrai preços ("A partir de R\$ X" para minimum_bid, "Avaliação
  Total R\$ X" para market_value), datas (1ª/2ª hasta) e endereço
  com fallback UF=RJ (Schulmann é RJ-only).
- Fixtures: 3 HTMLs reais (5240 sala Edif. Central, 5804 Angra,
  6393 Semirreboque — caso negativo).
- Testes: 4 casos em `tests/test_spider_schulmann_leiloes.py` cobrindo
  título correto, vehicle drop, source_lot_code, segundo imóvel.
- Smoke real: 47 lotes únicos de imóveis emitidos (~71 candidatos →
  ~24 vetos por veículo, ~0 por anchor missing).

## Não-trabalho intencional

- **paulobotelholeiloeiro / alinemarquesleiloeira** (mesmo template):
  precisaria estender `_LOT_PATH_PATTERNS` do genérico OU override de
  `_extract_lot_links`. Saiu de escopo "_fixup_item-only" — recon.
- **wrleiloes / nortedeminas**: precisaria seguir `/leilao/{id}` para
  enumerar lotes — também escopo maior.
- **leiloesfreire / cristianoescola**: Vue puro, exige XHR-first recon.

Recomendação: o batch D revela que os "fáceis" já caíram em A/B/C.
Daqui pra frente, ganho marginal por spider custom será pequeno
(<10 lotes/site na média) — investir nos providers SaaS compartilhados
(leilao_pro, leiloes_judiciais_br, suporte_leiloes) tem ROI maior.
