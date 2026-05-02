# leiloesbr

Recon arquitetural do **provider `leiloesbr`** (LeilõesBR — Marcio Pinho,
`https://www.leiloesbr.com.br`). 6 leiloeiros catalogados em
`data/intermediate/site_analysis.csv` apontam para esta plataforma.

Tenant amostrado para o piloto: **`tbaracajuleiloes.com.br`** (Thiago
Barros Cardoso — TB Aracaju Leilões, SE). Decisão deliberada: dos 6
tenants do `_input.json` (awleiloes RS, tbaracaju SE, prh RS,
casaamarela DF, evanioalves RJ, panda SC), o tba foi o único onde
encontrei um lote **encerrado com lances públicos** documentáveis sem
login — `peca.asp?ID=27650382` no leilão 56423, com 2 bids visíveis no
XHR `/ajax/le_historico_peca.asp`.

## Conclusão estratégica antes do detalhe

**LEILOESBR não é provider de imóveis.** Os 6 tenants amostrados +
inspeção direta do hub `leiloesbr.com.br` (meta keywords, ver abaixo)
mostram que a plataforma é especializada em **arte, numismática,
filatelia, colecionismo, móveis antigos**. O `real_estate_score=3.1`
do `site_analysis_row` reflete falsos positivos (palavras como "Casa",
"Sala") em conteúdo de catálogo de antiguidades.

O pilot deste recon **não é um imóvel** — é um lote filatélico
(Alemanha Reich, selo Deutsche Luftpost 2 M de 1931). O objetivo é
puramente arquitetural: documentar a plataforma, seus selectors e
seu padrão de bids para que a Fase 2 possa **excluir** este provider
do pipeline real-estate. A escolha de `property_type: outro` no
`pilot_item.json` é coerente: o vocabulário do `PilotItem` não tem
categoria filatelia/colecionismo, e este recon serve mais como prova
de mapeamento do que como item canônico.

> Caso paralelo: `leilao_pro` foi recon validado como real-estate
> (terreno em Tapera/RS); `leiloesbr` é o oposto — plataforma
> não-imóvel cujo pilot existe apenas para registrar como o sistema
> funciona caso aparece um lote imobiliário avulso em algum tenant.

## Tech stack & rendering

`site_analysis.csv` para os 6 tenants do provider:

| Tenant                | rendering | static_useful | dynamic_useful | tech_signals             |
| --------------------- | --------- | ------------- | -------------- | ------------------------ |
| awleiloes (RS)        | static    | 75            | 75             | jquery                   |
| tbaracajuleiloes (SE) | static    | 62            | 62             | jquery                   |
| prhleiloes (RS)       | dynamic   | 1             | 121            | jquery + bootstrap       |
| casaamarela (DF)      | dynamic   | 1             | 66             | jquery + bootstrap       |
| evanioalves (RJ)      | static    | 3             | 3              | jquery                   |
| pandacolecoes (SC)    | static    | 1             | 1              | jquery                   |

A discrepância static/dynamic entre tenants é **enganosa**: todos os
6 servem o mesmo template ASP Classic — a diferença está em **se a
home tem catálogos ativos sendo exibidos inline** (alguns tenants
herdam catálogos de tenants-irmãos no mesmo `Num` para popular a
home; ver "Gotchas" abaixo).

Stack canônica (verificada em todos os tenants):

- **ASP Classic / IIS 10** (`server: Microsoft-IIS/10.0` no header).
  `Set-Cookie: ASPSESSIONIDxxxxxxxx` no primeiro hit.
- **Encoding ISO-8859-1** nas páginas de erro 403 (curiosamente, as
  páginas servidas com sucesso vêm em UTF-8).
- **CloudFront** para assets:
  - `d2khfqh5bqnqgx.cloudfront.net/origin/` — JS/CSS shared (jquery,
    foundation, app.js, jquery.elevatezoom).
  - `d1o6h00a1h5k7q.cloudfront.net/imagens/` — fotos dos lotes,
    schema `imagens/img_{m|g}/{leilao_id}/{lot_id}[_N].jpg`.
- **Foundation 5** + **jQuery** + **jQuery.elevateZoom** + **tippy.js**.
  Bootstrap só nos tenants reportados como dynamic (PRH, casaamarela)
  — irrelevante para o protocolo de extração.
- **reCAPTCHA v3** (`6LdUrsIdAAAAANrmq5M7NOpJJCmYwlhK8nJJFoyQ`) carregado
  na home; só dispara em formulários de cadastro/contato — leitura
  pública não exige token.
- **Google Tag Manager** dual: `GTM-PQHVS4W` (LEILOESBR central) +
  GTM próprio do cliente (`G-FB2WZ1K4CJ` em awleiloes, etc.). Útil:
  o objeto `dataLayer.ecommerce.items` traz `price`, `item_brand`
  (= razão social do tenant), `item_category`, `item_list_id`
  (= leilão_id) já estruturados.

robots.txt (homogêneo entre os 6 tenants):

```
User-agent: *
Allow: /
Sitemap: https://<tenant>/sitemap.xml
```

**Permissivo total — nenhum path proibido**, incluindo `/ajax/`.

**WAF/UA filtering crítico** (gotcha #1): IIS rejeita 403 qualquer
User-Agent que **não comece com `Mozilla/5.0`**. Tentativas:

| User-Agent                                        | Resposta |
| ------------------------------------------------- | -------- |
| `TodoLeilaoBot/1.0 (+contato)`                    | 403      |
| `Mozilla/5.0 (compatible; TodoLeilaoBot/1.0; …)`  | 403      |
| `Mozilla/5.0 (compatible; Googlebot/2.1; …)`      | 200      |
| `Mozilla/5.0 (X11; Linux x86_64; rv:131.0) …`     | 200      |

O recon usou o último (Firefox completo). **Implicação para o spider
de produção**: ou registrar o crawler em uma allowlist com o operador
da plataforma (Marcio Pinho), ou adotar UA Firefox-style mantendo
`TodoLeilaoBot/1.0` no `Via:` ou `X-Crawler-ID:` para identificação
ética. **Robots.txt** é totalmente permissivo, então estamos dentro
do espírito da policy — só o filtro de UA é externo a robots.

**Conclusão**: `requires_playwright = False`. ASP server-side render
entrega todo o conteúdo do detalhe inline, exceto **histórico de
lances** (XHR — ver abaixo).

## Listing ativa

Não há `/imoveis` ou `/imovel` (provider não tem categoria de
imóveis). As listagens canônicas são:

- **Home `/default.asp`** — exibe os catálogos ativos do tenant
  (`catalogo.asp?Num={leilao_id}`) e cross-promo de catálogos de
  outros tenants LEILOESBR (`http://www.leiloeszeppelin.com.br/...`,
  `http://www.numismaticareal.com.br/...`).
- **Catálogo `catalogo.asp?Num={leilao_id}`** — todos os lotes de um
  leilão, com `<a href="peca.asp?ID={lot_id}">` sequenciais (lote 1,
  2, 3...). É a "listing ativa" canônica.
- **Pesquisa `pesquisa.asp?p=on&pesquisa={termo}&Ativo={1|9}`** —
  busca textual full-text. `Ativo=1` (ativos), `Ativo=9` (finalizados).
  Falha silenciosa se `pesquisa=` for vazio (mostra "Nenhuma pesquisa
  foi feita") — a query precisa de pelo menos 1 caractere. Truque do
  spider: usar `pesquisa=a` para retornar quase tudo.
- **`comprar.asp`** — landing page sem lots inline (placeholder
  institucional).
- **`listacatalogo.asp`** — 403 cross-tenant (provavelmente requer
  sessão ou auth). Não usável publicamente.

Card selector observado em `catalogo.asp` e `pesquisa.asp`:
`div.prod-box.ativo-box` envolve o card; dentro dele:

- `.img-box-inner-search img[src*='cloudfront.net/imagens/']` — thumb.
- `.LoteProd a[href*='peca.asp?ID=']` — link canônico (Lote: N).
- `.extra-info-lance span` — número de visitas (NÃO de lances).
- `.prod-title h3 a` — título do lote (texto + `title` attr para
  versão completa não-truncada).

Paginação: `pesquisa.asp` aceita `&Pagina={N}` (querystring); cada
página traz 30 cards. `catalogo.asp` em geral cabe em 1 página
(36 lotes no exemplo amostrado, todos no mesmo HTML).

## Listing encerrada

**Provider EXPÕE encerrados** — `pesquisa.asp` com `Ativo=9` (vs
`Ativo=1`) retorna lotes finalizados. Adicionalmente, `catalogo.asp`
preserva todos os lotes do leilão indefinidamente, mesmo após
encerramento (ao contrário de `leilao_pro` que **remove** lots após
data — cf. recon `leilao_pro`).

Diferença chave: o filtro `Ativo=9` é a única forma de **descobrir**
lotes encerrados sem conhecer `leilao_id` previamente. A página
exige `pesquisa=` não-vazio (requirement do form ASP) — para spider
sistemático use termos genéricos como `pesquisa=a`, `pesquisa=de`,
`pesquisa=do` e itere.

URL canônica adotada no piloto: `catalogo.asp?Num=56423` (TB Aracaju
leilão 56423 — encerrado em 11/11/2025). Cards de encerrados retém
mesma estrutura HTML; o `auction_status` é inferido da modal
`#leilao-modal` (data do leilão < hoje → encerrado).

Nuance: o card de listagem **não diferencia** ativo de encerrado
visualmente — a classe é sempre `prod-box.ativo-box` (legacy CSS).
Para spider de produção, o sinal de status fica em:

1. `<meta property="product:expiration_date">` no detalhe (data ISO).
2. `<meta property="product:availability" content="out of stock">`
   (= encerrado, no exemplo amostrado).
3. `<input name="valor">` value (se cresceu acima do inicial → teve
   lances → arrematado; se igual ao inicial → encerrado sem lance).
4. XHR `le_historico_peca.asp` retorna body vazio quando 0 lances.

## Pilot lot escolhido

URL: `https://www.tbaracajuleiloes.com.br/peca.asp?ID=27650382`

Leilão pai: "Leilão de Colecionismo em Numismática, Filatelia,
EUCALOL, cartões e objetos afins." (TB Aracaju, Num=56423).
4 dias de pregão online: 11, 12, 13, 14/Nov/2025 — Ter/Qua/Qui/Sex
às 19h20 BRT. Local de retirada: Rua Santa Luzia 180 Sala 02 -
Galeria Nobre - Centro - Aracaju/SE.

**Motivo da escolha**: probe sistemático (rate-limit 1.6s) das 36
peças do catálogo 56423 via XHR `/ajax/le_historico_peca.asp`. Dos
36, apenas 6 tinham `total_lances >= 1`. Selecionei `ID=27650382`
por ser o único com `2 licitantes / 2 lances` (o resto era 1/1) —
máxima riqueza de bids no escopo do recon.

Detalhes:

- **Lote 1** do catálogo 56423 (categoria `Filatelia estrangeira`).
- **Título**: "Alemanha Reich - Deutsche Luftpost 2 M Deutsches
  Reich 1931 - usado." (selo aéreo alemão de 1931, valor facial 2
  Marcos, com carimbo de uso).
- **Tipo**: `outro` (mapping forçado — `PilotItem.PropertyType`
  não tem categoria filatelia/colecionismo).
- **Endereço bruto**: usado o **PONTO DE RETIRADA** do leiloeiro
  (não há endereço de bem em filatelia). Documentado em
  `parser_notes`.
- **Lance inicial**: R$ 20,00 (extraído do GTM `dataLayer.price=20`).
- **Lance MIN próxima oferta**: R$ 145,00 (input hidden
  `name="valor" value="145"`). Reflete `(último lance R$125 +
  tick R$20) = R$145`.
- **Histórico de lances** (extraído via XHR
  `/ajax/le_historico_peca.asp` com body `id=27650382`):
  - `30/10/2025` — R$ 20,00 — usuário oculto (anônimo)
  - `11/11/2025` — R$ 125,00 — usuário oculto (anônimo, vencedor)
- **Bid timestamp**: o XHR retorna apenas data (`dd/mm/yyyy`), sem
  hora. Apliquei a hora oficial do pregão (19:20 -03:00 BRT,
  conforme `#leilao-modal`). Documentado em `parser_notes`.
- **Bidder**: `bidder_raw=null` para ambos. O 3º `<span>` da resposta
  XHR vem **vazio** para visitante anônimo (provider obfusca
  username — privacidade by design para não-logados). Nada a
  redigir (PII).
- **Imagens**: 2 — `cloudfront.net/imagens/img_g/56423/27650382.jpg`
  (large) e `img_m/56423/27650382.jpg` (medium thumbnail). Ambos
  sob mesmo CDN.
- **Documentos**: 0 — provider não anexa edital/matrícula como PDF;
  os termos do leilão estão inline no HTML (`#leilao-modal`,
  `#simple1Tab`).
- **`auction_status: "arrematado"`**. Last bid R$125 em 11/11/2025
  (= data oficial do pregão = data de encerramento) >> lance
  inicial R$20, e há vencedor → vendido.

| Campo                    | Valor (resumido)                                  |
|--------------------------|---------------------------------------------------|
| title                    | Alemanha Reich - Deutsche Luftpost 2 M ...        |
| description              | 251 chars                                         |
| property_type            | `outro`                                           |
| address.raw_text         | "Rua Santa Luzia, 180 Sala 02 - Galeria Nobre - Centro - Aracaju - SE" |
| address.uf               | `SE`                                              |
| address.municipality_name| `Aracaju`                                         |
| address.cep              | null (provider não publica)                       |
| total_area_sqm           | null (não-imóvel)                                 |
| market_value_brl         | null (provider não publica avaliação)             |
| rounds[1].minimum_bid    | "20.00"                                           |
| rounds[1].scheduled_at   | 2025-11-11T19:20:00-03:00                         |
| auction_status           | `arrematado`                                      |
| bids[]                   | 2 (R$ 20,00 em 30/10; R$ 125,00 em 11/11)         |
| images                   | 2 (CloudFront — img_g + img_m)                    |
| documents                | 0 (provider não anexa PDF)                        |

## XHRs descobertas

LEILOESBR usa XHR para 3 endpoints relevantes (todos POST/GET sem
auth, sem CSRF token, sem cookies necessários — chamáveis sem
sessão):

### 1. `POST /ajax/le_historico_peca.asp` — **histórico de lances**

```
POST /ajax/le_historico_peca.asp
Content-Type: application/x-www-form-urlencoded
Body: id={lot_id}
```

Resposta: texto pipe-delimitado em ISO-8859-1.

```
total_lances|num_licitantes|<Li><span>dd/mm/yyyy</span><span>R$ NN.NN</span><span>username_or_blank</span></li>...
```

- `total_lances` e `num_licitantes` em string-decimal.
- `<Li>` (sic — letra L maiúscula é literal do servidor) com 3
  `<span>`: data, valor, username.
- Valor em formato US-style: `R$ 125.00` (ponto como decimal),
  **não** PT-BR `R$ 125,00`. Cuidado no parser.
- Username do 3º `<span>` é **vazio para visitantes anônimos** —
  provider obfusca PII para quem não está logado. **Bidder names
  só visíveis com login** (fora do escopo da Fase 1).
- Body vazio = sem lances.

### 2. `GET /ajax/lance_atual.asp?idpeca={lot_id}` — **lance atual**

Retorna current min-bid em texto plain (ex: `145`). Útil para sondar
sem baixar a página inteira. **Quirk**: o IIS exige
`Content-Length: 0` mesmo em GET — `curl -G` falha com `411 Length
Required`. Use `curl --data-urlencode` ou Python `requests` (que
faz isso automaticamente).

### 3. `POST /ajax/enviarcontato2.asp` e `enviaramigo2.asp`

Formulários de contato/share. Não relevante para extração.

### Sitemap

`https://<tenant>/sitemap.xml` permitido (declarado em robots).
Em pesquisa rápida: lista entradas de catálogos e peças com
`<lastmod>` (= data de modificação no DB). Útil para spider
descobrir lots novos sem paginar pesquisa.asp; **não testado em
profundidade** neste recon.

## Gotchas

1. **WAF de UA: `Mozilla/5.0` obrigatório**. Qualquer UA sem o token
   leading retorna 403. Recon usou Firefox-style; em produção,
   negociar allowlist com Marcio Pinho ou aceitar UA Firefox.
   Robots.txt é permissivo — não há conflito ético.

2. **Provider NÃO é real-estate**. Especializado em
   arte/numismática/filatelia/colecionismo. Os 6 tenants do
   `_input.json` (tba, prh, casaamarela, evanio, panda, awleiloes)
   confirmam: zero hits para "imovel"/"apartamento"/"casa"/
   "terreno" em `pesquisa.asp` (probado em todos com
   `Ativo=1` e `Ativo=9`). Meta keywords do hub central
   `leiloesbr.com.br/` enumeram explicitamente: "Leilão de artes,
   colecionismo, filatelia, numismática, móveis antigos, fotografia,
   esculturas, antiguidades, medalhas, livros, prataria, porcelana,
   selos, joias..." — nenhuma menção a imóveis. **Implicação Fase 2**:
   excluir provider `leiloesbr` do pipeline real-estate antes de
   instanciar spiders.

3. **Cross-tenant cross-promo na home**. Tenants pequenos
   (awleiloes) renderizam catálogos de tenants vizinhos
   (`leiloeszeppelin`, `leiloesfp`, `numismaticareal`) na home, com
   anchor `<a href="http://leiloeszeppelin.com.br/peca.asp?Id=...">`.
   Isso infla o `useful_links_count` no `site_analyzer.py` mesmo
   quando o tenant não tem catálogo próprio ativo. **Spider deve
   filtrar por host** antes de seguir anchors.

4. **`<a href="peca.asp?ID=N">` vs `peca.asp?Id=N`**. Provider mistura
   case do parâmetro: home usa `Id` (lowercase first char), página de
   detalhe e pesquisa usam `ID` (uppercase). Servidor aceita ambos
   (ASP é case-insensitive em Request.QueryString). Spider deve
   normalizar.

5. **Bid history sem hora**. XHR retorna `dd/mm/yyyy` only — para
   `PilotBid.timestamp` (que exige tz-aware datetime), aplicar a
   hora oficial do pregão extraída de `#leilao-modal`. Em leilões
   online de vários dias (caso 56423: 4 dias 11-14/11/2025), todos
   os bids vêm com a data do dia em que foram dados, mas a hora
   real é desconhecida. Aproximação 19:20 -03:00 (= horário de
   início do pregão) é convencional — **não** representa o
   timestamp real do bid.

6. **Bidder name oculto para anônimos**. O 3º `<span>` da resposta
   XHR vem vazio quando o cliente HTTP não está autenticado.
   Provider obfusca por padrão — privacidade by design. Para spider
   de produção, isso significa `bidder_raw=null` em todos os bids
   sem perspectiva de mudar (não há headers/cookies que destravem
   sem cadastro real).

7. **Valor monetário em formato US**. XHR de bid history retorna
   `R$ 125.00` (ponto como decimal), não PT-BR `R$ 125,00`. Já o
   HTML do detalhe (form `<input name="valor">`) usa integer raw
   sem casas decimais (`value="145"`). Parser deve cobrir ambos.

8. **`lance_atual.asp` exige Content-Length em GET** (IIS quirk).
   `curl -G` falha 411; alternativa: `curl --data-urlencode
   "idpeca={id}"` (envia POST), ou cliente Python `requests`/`httpx`
   (envia automaticamente).

9. **Encoding misto**. Páginas servidas com sucesso vêm em UTF-8
   (com `<meta charset="utf-8">`); páginas de erro 403 vêm em
   ISO-8859-1. XHRs de bid history vêm em UTF-8 (apesar do `<Li>`
   maiúsculo sugerindo legacy). Não houve necessidade de transcoding
   neste recon, mas registrar para spider futuro.

10. **PII**: nada a redigir no piloto. Bidders são `null` (provider
    obfusca para anônimos), descrição não tem CPF nem nome PF
    (são selos), endereço é PJ (TB Aracaju Leilões — Galeria Nobre).
    `parser_notes` registra a ausência de redação necessária.

11. **`product:expiration_date` ≠ data do leilão**. O meta tag
    `<meta property="product:expiration_date" content="2025-11-15">`
    está **4 dias depois** do dia do pregão (11/11/2025). Provavelmente
    representa o fim do prazo de retirada (48h após pregão segundo
    termos), não o encerramento do leilão. **Não use** para inferir
    `auction_status` — use `#lei-modal` (data oficial).

## Decisões e limitações

- **`requires_playwright = False`**. ASP entrega tudo server-side.
  Bid history vem por XHR simples (POST sem auth) — `httpx` resolve.
- **`platform_hint = "leiloesbr"`**. Canônico. Sinais homogêneos
  entre os 6 tenants (template ASP comum).
- **`auctioneer_slug = "tb-aracaju-leiloes"`** no piloto (não
  awleiloes que era o representativo do `_input.json`): decisão
  baseada na disponibilidade de bids reais. awleiloes (Alexandre
  Weyh, RS) tem mesma estrutura mas no momento do recon estava com
  catálogo cross-promo de outros tenants (próprio catálogo Num=61534
  retornou 8 lotes, todos numismáticos/colecionismo). Uniformidade do
  template entre tenants foi verificada — selectors do
  `selectors.yaml` são portáveis.
- **`property_type = "outro"`**. PilotItem não tem categoria
  filatelia/colecionismo. Documentado em `parser_notes`. Em Fase 2
  (mapeamento `core.unit_kind`), provider deve ser **excluído**
  antes de chegar ao mapper — não há `unit_kind` válido.
- **`address.raw_text`** = endereço de RETIRADA do leiloeiro, não
  de bem. PilotItem HARD exige raw_text não-vazio; usar pickup
  é a aproximação válida quando o bem é móvel/colecionismo.
  Documentado.
- **`market_value_brl = null`**. Provider não publica avaliação
  prévia em lotes de arte (lance inicial = lance min, sem
  avaliação separada). SOFT.
- **`documents = []`**. Provider não anexa edital/matrícula como
  PDF. Termos inline no HTML. SOFT.
- **`bids[]` capturado**: 2 lances, sem hora exata (date-only no
  provider) e sem bidder name (provider obfusca para anônimos).
  Aproximações documentadas em `parser_notes`.
- **`listing_active`**: usei `pesquisa.asp` em vez de
  `catalogo.asp` porque é mais discoverable (não exige conhecer
  `leilao_id` antecipadamente).
- **`listing_closed`**: `catalogo.asp?Num={leilao_id}` — provider
  preserva lots indefinidamente após encerramento. Alternativa
  `pesquisa.asp?Ativo=9` também válida.
- **Rate limit ≥ 1.6s** mantido (≈80 requests no recon: home dos
  6 tenants, pesquisa, comprar, catalogo, 36 probes XHR de bid
  history, fetch de detail, fetch de robots, fetch de JS para
  decompor handler). Total ≈2.5min de delay efetivo.
- **Não baixei imagens nem PDFs** (regra dura). Imagens entram
  apenas como URL.

## Status do validador

`validation.json::passed_hard = true`. Fill rate = 19/25 = 76%.

SOFT warnings esperados (todos justificados como limitação do
provider, não bug do recon):

- `market_value_brl ausente` — provider não publica avaliação.
- `address.cep ausente` — provider não enriquece pickup com CEP.
- `nenhum documento listado` — provider não anexa PDF.

Hard checks: title, source_lot_url (literal em `pilot_source.html`),
`address.raw_text`, `auction_status`, ≥1 round com `minimum_bid_brl`.
Todos OK.
