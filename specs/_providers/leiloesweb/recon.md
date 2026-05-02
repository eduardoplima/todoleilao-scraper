# leiloesweb

Recon arquitetural do **provider `leiloesweb`** (Leilões Web —
plataforma white-label brasileira para leiloeiros oficiais). 3 sites
catalogados no `_input.json`: leiloeslaraforster.com.br (rep, RS),
bampileiloes.com.br (SC), selectleiloes.com.br (SP). Os 3 servem o
mesmo template (encoding ISO-8859-1, footer "© Copyright, Leilões
Web", meta `<meta name="author" content="Leilões Web - www.leiloesweb.com.br/" />`).

Tenant amostrado para o piloto: **`bampileiloes.com.br`** (Ricardo
Bampi — Lages/SC). Decisão deliberada: dos 3 tenants, Bampi tinha
**271 leilões** na home contra 6 (Lara) e ~3 (Select); mais volume
de imóveis e leilões finalizados — único onde encontrei lote
encerrado **com lance público** em 2026 (leilão 1233 / lote 1509,
arrematado em 28/04/2026 por R$ 1.570.936,81).

## Tech stack & rendering

`site_analysis.csv` representativo (Lara Forster):

| Campo                       | Valor                       |
| --------------------------- | --------------------------- |
| rendering                   | static                      |
| static_useful_links         | 610                         |
| dynamic_useful_links        | 609                         |
| tech_stack                  | jQuery; Bootstrap           |
| tech_signals                | jquery, bootstrap, server:nginx |
| requires_js_for_listings    | False                       |

Stack canônica (verificada nos 3 tenants):

- **Backend ASP/PHP misto** (URL `/leilao/detalhe_leilao/<id>`
  parece rota PHP-style; XHR `/principal/sistemas/leilao/lotes_regressivas.php`
  é PHP explícito; `/principal/sistemas/leilao/login.php`, etc).
- **Encoding ISO-8859-1** declarado em `<meta charset="iso-8859-1">`
  e respeitado server-side (UTF-8 quebra leitura de acentos em
  descrições). **Crítico** para o spider — usar `decode("iso-8859-1")`.
- **nginx** (header server).
- **jQuery + Bootstrap** + countdown widget (`$('#regressiva').countdown(...)`)
  para timer de 1ª/2ª praça.
- **reCAPTCHA v3** (`6LeD6o8gAAAAALoEOERg5M4bjOT6tI-i6rYX_4W1`) carregado
  na home; só dispara em formulários de cadastro/login. Leitura pública
  não exige token.
- **Open Graph e tags Facebook** (fb:app_id, og:title, og:image)
  configuradas, mas **sem og:url ou link rel=canonical** — uma das
  maiores limitações para proveniência (ver Decisões).
- **Schema URL convention** (homogêneo entre tenants):
  - Listagem ativa: home `/` + `/busca/avancada` (form POST)
  - Detalhe leilão: `/leilao/detalhe_leilao/{leilao_id}` (com `#conteudo`
    fragment para scroll)
  - XHR de status/lances: `/principal/sistemas/leilao/lotes_regressivas.php?idLote={lot_id}`
  - Imagens lote: `/manage/pub/Image/{timestamp}{nome}.jpg` (e `/principal/pub/Image/...`
    como mirror — mesmo conteúdo, paths diferentes, ver Gotchas)
  - PDFs: `/principal/pub/Image/*.pdf` (matrículas, anexos)
    e `/principal/pub/anexos/*.pdf` (editais — mais novo)
  - Auditório/transmissão: `/principal/sistemas/leilao/auditorio_arrematante.php?id_leilao={leilao_id}&data={dd/mm/yyyy}#pg1`

robots.txt (idêntico nos 3 tenants):

```
User-agent: *
Disallow:
Disallow: /manage
```

**Permissivo geral, mas `/manage/*` é proibido**. As fotos têm 2 paths
duplicados: `/manage/pub/Image/<file>.jpg` (proibido) e
`/principal/pub/Image/<file>.jpg` (permitido). **Spider deve preferir
`/principal/pub/Image/`** para o fetch real; o pilot lista o `/principal/`
canônico no `pilot_item.json`. PDFs estão sempre em `/principal/`,
sem ambiguidade.

User-Agent: o servidor aceita `Mozilla/5.0 (compatible; TodoLeilaoBot/1.0; +contato)`
sem rejeição (testado em todos os 3 tenants — HTTP 200). Ao contrário
de leiloesbr, **não há WAF de UA**.

**Conclusão**: `requires_playwright = False`. Páginas server-side
rendered; todo conteúdo do detalhe (descrição, endereço, docs, tabela
de bids inline) está no HTML inicial. O XHR `lotes_regressivas.php`
existe mas é redundante para extração — apenas mais limpo (JSON
estruturado) e atualiza o status em tempo real durante o pregão.

## Listing ativa

Home `/` consolida todos os leilões do tenant em cards homogêneos
`div.box-leilao` (271 cards no Bampi, 47 no Lara, ~30 no Select).
Cada card é UM **leilão** (não um lote) e contém:

- Anchor `<a href="https://<tenant>/leilao/detalhe_leilao/{leilao_id}#conteudo">`
- Título (e.g., "1372/2026 Judicial Apartamento - 2 vagas garagem - Jurerê")
- Vara (e.g., "QUARTA VARA CÍVEL DE LAGES/SC")
- 1ª/2ª Leilão: data + hora + lance inicial
- Modalidade (Online | Presencial | Simultâneo)
- Quantidade de lotes (`1 lote(s)`, `2 lote(s)`, etc)

Card selector escolhido:
`div.box-leilao a[href*='/leilao/detalhe_leilao/']` (CSS).

**Paginação**: `none` — provider preserva todos os leilões na home
indefinidamente, sem paginação. Para Bampi são 271 cards no
`pilot_listing.html` (824KB).

Alternativa: `/busca/avancada` é form POST com filtros (`vara`,
`tipo_leilao`, `tipo_bem`, `data_ini`, `data_fim`, etc). `tipo_bem=10`
= "Imóvel". Útil para spider sistemático com filtragem fina, mas
duplicaria o que a home já entrega.

## Listing encerrada

**Provider EXPÕE encerrados na mesma listagem ativa.** A home contém
ativos + encerrados misturados, sem distinção visual no card —
status real só aparece após XHR.

`listing_closed.url_pattern = listing_active.url_pattern` no
`selectors.yaml`: o spider deve iterar todos os cards da home e,
para cada `leilao_id`, fetchar `/leilao/detalhe_leilao/{leilao_id}`
para descobrir o(s) `idLote`(s) (regex `idLote=(\d+)` no HTML), depois
hit no XHR `lotes_regressivas.php?idLote={lot_id}` para classificar:

| `statusLote` (XHR) | `auction_status` (canônico) | Tem bids? |
| ------------------ | --------------------------- | --------- |
| `Arrematado`       | `arrematado`                | sim, ≥1   |
| `ENCERRADO`        | `encerrado`                 | hist=[]   |
| `Fechado`          | `encerrado`                 | hist=[]   |
| `Suspenso`         | `suspenso`                  | hist=[]   |
| `Aberto`/em pregão | `ativo`                     | possível  |

Datas das praças em `.lote-details` no HTML do detalhe; spider pode
inferir `auction_status=ativo` quando todas as praças são futuras
(today < data 1ª praça) sem precisar do XHR.

**Critério de descoberta sistemática**: probei 19 candidatos com
imóveis e datas no passado (2015-2026). Resultado: 17/19 ENCERRADO
com 0 lances, 2/19 Arrematado com 1+ lance. Ratio de encerrados-com-bids
no Bampi é ~10% — é raro, mas público.

## Pilot lot escolhido

**URL detalhe**: `https://www.bampileiloes.com.br/leilao/detalhe_leilao/1233`

**URL canônica do lote (XHR)**:
`https://www.bampileiloes.com.br/principal/sistemas/leilao/lotes_regressivas.php?idLote=1509`

**Leilão 1372/2026** (4ª Vara Cível de Lages/SC) — penhora de
apartamento + 2 vagas de garagem no Edifício Residencial "Solar das
Algas", Av. das Algas 1109, Jurerê Internacional, Florianópolis/SC.

**Motivo da escolha**:

1. Único leilão entre os 19 probados que tinha `statusLote=Arrematado`
   COM `historico` não-vazio (1 lance) E imagem (`FOTO_-_AN_NCIO.jpg`).
2. Imóvel residencial "puro" (apartamento + garagens), não fração
   ideal nem terreno rural — facilita o mapeamento `property_type=apartamento`.
3. Encerrado em 28/04/2026 (3 dias antes do recon = 2026-05-01) →
   provider ainda mantém estado completo (lance, bidder, timestamp).

Detalhes:

- **Lote 1509** (único do leilão 1233, "1 lote(s)").
- **Título**: "Apartamento - 2 vagas garagem - Jurerê" (do card da home);
  `pilot_item.title` enriquecido com vara e código do leilão.
- **Tipo**: `apartamento` (claro do título e descrição).
- **Endereço bruto**: usado o **endereço do bem** (Av. das Algas 1109,
  Jurerê, Florianópolis/SC), não o da vara nem da localização-de-leilão
  (Lages/SC). Documentado em parser_notes.
- **Lance inicial 1ª Praça** (22/04/2026 14h00): R$ 2.101.338,30
  (= avaliação atualizada).
- **Lance inicial 2ª Praça** (28/04/2026 14h00): R$ 1.470.936,81
  (~70% da avaliação).
- **Avaliação (market_value_brl)**: R$ 2.101.338,30 (atualizada
  25/09/2024 sobre o R$ 1.984.726,64 original).
- **Histórico de lances** (1 lance, do XHR `historico[]`):
  - 28/04/2026 10:55:06 — R$ 1.570.936,81 — bidder "Zero1" (apelido
    público; CPF mascarado `697.947.07***` na tabela HTML mas omitido
    do JSON XHR; preferi o XHR e descartei a tabela para evitar PII
    residual).
  - **Bid timestamp**: vem com data+hora no XHR (`28/04/2026 10:55:06`).
    Aplicado tz `-03:00` (BRT).
  - Lance veio antes da abertura formal da 2ª praça (10:55 < 14:00) —
    isso é normal no leiloesweb: durante o "leilão online" o sistema
    aceita lances antecipados que entram na 2ª praça; o ApiCore
    determina arrematação após o tempo regressivo.
- **Imagens**: 1 — `FOTO_-_AN_NCIO.jpg` em
  `/principal/pub/Image/20260323025920FOTO_-_AN_NCIO.jpg`. Provider
  não publicou múltiplas fotos para este imóvel (gotcha conhecido —
  alguns lotes de alto valor entram com foto-banner única).
- **Documentos**: 4 PDFs:
  - Edital — `/principal/pub/anexos/20260323113819Edital.pdf`
  - Matrícula 96.172 (apartamento) — `/principal/pub/Image/20260304052243Matricula_96172_cod58191.pdf`
  - Matrícula 96.223 (garagem 37) — `/principal/pub/Image/20260304052243Matricula_96223_cod64350.pdf`
  - Matrícula 96.224 (garagem 38) — `/principal/pub/Image/20260304052243Matricula_96224_cod12180.pdf`
- **Encumbrances** (`encumbrances_raw[]`, 5 ônus extraídos):
  Penhora AV-4, Indisponibilidade AV-5, IPTU 2025 R$5.044,01, IPTU
  parcelado em execução fiscal R$8.210,75 (suspenso até 19/10/2035),
  débito de condomínio a consultar.
- **`auction_status: "arrematado"`** (canônico). Status raw de cada
  round em `rounds[].status_raw`.

| Campo                    | Valor (resumido)                                  |
|--------------------------|---------------------------------------------------|
| title                    | Apartamento - 2 vagas garagem - Jurerê (Leilão 1372/2026) |
| description              | 1141 chars (Bem 1+2+3 + ônus + avaliação)         |
| property_type            | `apartamento`                                     |
| address.raw_text         | Av. das Algas, 1109, Jurerê Internacional, Florianópolis/SC |
| address.uf               | `SC`                                              |
| address.municipality_name| `Florianópolis`                                   |
| address.cep              | null (provider não publica)                       |
| area_sqm                 | "152.83" (privativa apto)                         |
| total_area_sqm           | "190.82" (privativa+comum apto)                   |
| market_value_brl         | "2101338.30" (avaliação atualizada)               |
| rounds[]                 | 2 (1ª/2ª praça)                                   |
| auction_status           | `arrematado`                                      |
| bids[]                   | 1 (R$ 1.570.936,81 em 28/04/2026 por "Zero1")     |
| images                   | 1 (FOTO_-_AN_NCIO em /principal/pub/Image/)       |
| documents                | 4 (Edital + 3 matrículas)                         |
| encumbrances_raw         | 5                                                 |

## XHRs descobertas

leiloesweb usa um único XHR canônico para status + bids:

### `GET /principal/sistemas/leilao/lotes_regressivas.php?idLote={lot_id}` — **status + histórico**

Sem auth, sem CSRF, sem cookies. Resposta JSON UTF-8.

```
GET /principal/sistemas/leilao/lotes_regressivas.php?idLote=1509
Headers: User-Agent: Mozilla/5.0... (qualquer UA aceito)
Resposta:
{
  "id_lotes": "1509",
  "statusLote": "Arrematado",
  "classStatusLote": "arrematado",
  "isContagem": "1",
  "is_fechado": "0",
  "is_arrematado": "0",     // (sic — o JS usa o campo isArrematado abaixo)
  "is_suspenso": "0",
  "isCondicional": null,
  "descUltimoLance": "Ultimo lance R$ 1.570.936,81",
  "html_ultimo_lance": "",
  "lance_nick": "Zero1",
  "lance_valor": "R$ 1.570.936,81",
  "lance_ip": "189.34.20.150",
  "lance_data": "28/04/2026 10:55:06",
  "lance_inc1": "1.571.936,81",
  "lance_inc2": "1.572.936,81",
  "lance_inc3": "1.573.936,81",
  "contagem_inicio": "180",
  "isEncerrado": "0",
  "tipo_regressiva": "1",
  "status_regressiva": "0",
  "isFechado": "1",
  "isArrematado": "1",
  "isSuspenso": 0,
  "tempoRestante": -271802,
  "historico": [
    {
      "id_lance": "1404",
      "val_lance": "R$ 1.570.936,81",
      "val_comissao": "R$ 78.546,84",
      "val_total": "R$ 1.649.483,65",
      "pagamento": "A vista",
      "ip": "189.34.20.150",
      "data_lance": "28/04/2026 10:55:06",
      "origem": "ONLINE",
      "nick_name": "Zero1"
    }
  ]
}
```

Campos relevantes para Fase 1:

- `statusLote` — texto canônico (Arrematado | ENCERRADO | Fechado |
  Suspenso | em pregão).
- `historico[]` — lista de bids estruturada. **NÃO expõe CPF** (só
  apelido em `nick_name`), embora a tabela HTML do detalhe exponha
  CPF parcial mascarado. Preferir o XHR.
- `lance_data` — formato `dd/mm/yyyy HH:MM:SS`, sem TZ (assumir
  `-03:00`).
- `val_lance` — formato PT-BR `R$ 1.570.936,81` (vírgula decimal,
  ponto milhar). Cuidado no parser.
- `lance_ip` / `historico[].ip` — IP do bidder. **PII potencial** —
  spider deve omitir.

Frequência de polling: o JS chama o XHR a cada 4 segundos durante
o pregão (`setTimeout(atualizaLote, 4000)`). Para spider de extração
estável (não real-time), 1 hit por lote é suficiente.

### Sem outros XHRs relevantes

- `/principal/sistemas/leilao/login.php` — POST de auth (não usar).
- `/principal/sistemas/leilao/auditorio_arrematante.php` — página
  HTML do auditório (transmissão ao vivo). Não traz dados extra.

### Sitemap

Não testado neste recon. `/sitemap.xml` não declarado em robots.txt
para os 3 tenants (`Disallow:` vazio = allow tudo, sem `Sitemap:`).
Para spider de produção, vale tentar `/sitemap.xml` antes de
crawlear pela home.

## Gotchas

1. **Encoding ISO-8859-1** server-side. Acentos quebram com UTF-8
   (`á` vira `0xe1` raw; reescrita errada vira `Ã¡`). Spider DEVE usar
   `response.encoding = 'iso-8859-1'` ou equivalente. (httpx faz auto-detect
   pelo `<meta charset>` em geral, mas Scrapy é mais agressivo —
   forçar.)

2. **Sem self-canonical URL**. A página `/leilao/detalhe_leilao/{id}`
   não inclui og:url, link rel=canonical, nem auto-anchor. Implicação
   para o pilot: `source_lot_url` precisa ser uma URL que aparece no
   HTML para passar a checagem de proveniência do validador. **Decisão**:
   usar a URL canônica do XHR `lotes_regressivas.php?idLote={lot_id}`
   — aparece literalmente no HTML (em `function atualizaLote() { url:
   '...?idLote=1509'`), identifica unicamente o lote, e é o endpoint
   real de fetch para o spider. Spider de produção pode preservar a
   URL "humana" `/leilao/detalhe_leilao/{leilao_id}` em outro campo
   (`core.auction.source_url` ou metadata) — mas para o piloto, XHR
   URL é o ground truth.

3. **`/manage/*` é Disallow no robots.txt**. Mas as imagens dos lotes
   tem mirror em `/manage/pub/Image/<file>.jpg` E `/principal/pub/Image/<file>.jpg`.
   Spider DEVE usar `/principal/` (permitido). Pilot lista
   `/principal/pub/Image/...FOTO_-_AN_NCIO.jpg` no `images[]`.

4. **Localização do bem ≠ localização do leilão**. O card da home traz
   `Localização: LAGES/SC` (cidade da vara), mas o **bem** está em
   `Florianópolis/SC` (Av. das Algas). Spider deve extrair endereço
   do bloco "Endereço de vistoria:" dentro de "Descrição detalhada do
   Lote", não da metadata do leilão.

5. **`description` mistura múltiplos bens**. Quando o leilão tem mais
   de um bem (apto + garagens), a descrição enumera "Bem 1: ...
   Bem 2: ... Bem 3: ...". Para `PilotItem` em Fase 1, capturei tudo
   na descrição e usei o **Bem 1** (o principal — o apartamento) para
   `address.*` e `area_sqm`. Em Fase 2 isso vira N `core.auction_lot`
   irmãos com mesmo `auction_id`, ou um `auction_lot` master com
   `spatial_unit[]`.

6. **CPF parcial mascarado na tabela HTML**. Coluna "usuário/placa"
   da tabela "Histórico de lances recebidos" expõe `Zero1 CPF: 697.947.07***`.
   Apenas 6 dígitos visíveis (3+3) + ` *** `. Não é CPF completo, mas
   é PII parcial (combinado com IP no mesmo row, é potencialmente
   re-identificável). **Spider DEVE preferir o JSON XHR** que omite o
   CPF inteiramente.

7. **IP do bidder no XHR**. `historico[].ip` traz o IP IPv4 público do
   bidder (e.g. `189.34.20.150`). Em Fase 1 redigi `bids[].bidder_raw`
   para incluir apenas o `nick_name` ("Zero1"). IP descartado.

8. **Lance antes do horário formal da praça**. Bidders podem dar lances
   antes do horário oficial (10:55 vs 2ª praça 14:00). Não invalida o
   bid — entra na contagem da 2ª praça. Spider não deve filtrar por
   data.

9. **Datetimes do XHR sem TZ**. `lance_data: "28/04/2026 10:55:06"` —
   sem fuso. Provider opera Brasília `-03:00` (Lages/SC, Florianópolis/SC).
   Aplicar tz BRT no parsing.

10. **Valores monetários PT-BR no XHR**. `R$ 1.570.936,81` (ponto
    milhar, vírgula decimal). NÃO confundir com leiloesbr (que usa
    formato US `R$ 125.00`). Parser deve cobrir só PT-BR aqui.

11. **`is_arrematado` vs `isArrematado` no XHR**. O JSON tem AMBOS:
    `is_arrematado: "0"` (sempre 0, parece) e `isArrematado: "1"` (o
    correto). Usar `isArrematado` (camelCase) ou inferir de `statusLote`.

12. **PII**: `bidder_raw="Zero1"` é apelido — público em contexto de
    leilão; mantém. Sem CPF, sem nome PF, sem agentes públicos a redigir
    no piloto. Endereço do bem é PJ implícita (condomínio); descrição
    cita matrículas (números de cartório, públicos). Sem redação
    necessária.

13. **`tempoRestante` negativo**. No XHR de leilões já encerrados,
    `tempoRestante: -271802` (segundos negativos = quanto tempo passou
    desde o fim). Spider pode usar como sinal de `auction_status =
    encerrado | arrematado`.

## Decisões e limitações

- **`requires_playwright = False`**. SSR completo; XHR opcional para
  status estruturado.
- **`platform_hint = "leiloesweb"`**. Canônico (footer + meta author
  identificam a plataforma).
- **`auctioneer_slug = "ricardo-bampi"`**. Tenant amostrado, escolhido
  por volume e disponibilidade de leilão arrematado-com-bid em data
  recente. Os 3 tenants compartilham template — selectors são
  portáveis (verificado por inspeção visual em `lara_home.html` e
  `bampi_home.html`; mesmas classes CSS, mesma estrutura de
  `box-leilao`).
- **`source_lot_url`** = XHR URL `lotes_regressivas.php?idLote=1509`
  (não `/leilao/detalhe_leilao/1233`) — explicado em Gotcha #2.
  Trade-off: URL humana fica no comentário do `selectors.yaml` e em
  `parser_notes`. Spider de produção pode duplicar (`auction.source_url`
  = leilao detalhe; `auction_lot.source_url` = XHR).
- **`address.cep = null`**. Provider não publica CEP nem na descrição
  nem no endereço de vistoria. SOFT — única warning do validador.
- **`area_sqm = 152.83`** = privativa do apto. Não somo as áreas das
  garagens (Bem 2 + Bem 3 = 12 + 12 = 24m²) porque são lotes irmãos,
  não parte da unidade habitacional. **`total_area_sqm = 190.82`** =
  total do Bem 1 (privativa + comum). Provider não publica área de
  terreno isoladamente (só fração ideal: 4,09665% de 1.861,60m² =
  ~76,26m²) — não usei.
- **`bids[]`** capturado: 1 lance, do XHR. Bidder `Zero1`, sem CPF,
  sem IP. Datetime tz-aware (`2026-04-28T10:55:06-03:00`).
- **`encumbrances_raw[]`** populado com 5 ônus extraídos manualmente
  da seção "Ônus" + "Informações" + "Débitos" da descrição. Spider
  deve fazer parsing programático em Fase 2.
- **`listing_active` = `listing_closed`** (mesma URL home). Provider
  não distingue ativos de encerrados na listagem; status só após XHR.
  Documentado em comentário no `selectors.yaml`.
- **Rate limit ≥ 1.6s** mantido durante o recon (~50 requests
  totais: home dos 3 tenants, busca/avancada do Lara, 19 detalhe_leilao
  + 19 XHRs no Bampi, fetch repetido do detalhe pilotado para
  proveniência). Total ≈80s de delay efetivo.
- **Não baixei imagens nem PDFs** (regra dura). Imagens e docs entram
  apenas como URL no `pilot_item.json`.
- **Os 3 tenants compartilham template idêntico**. Recon é
  arquitetural — o spider de leiloesweb trata os 3 (e provavelmente
  outros não catalogados) com o mesmo código, parametrizando apenas
  o `host`. Bampi foi o cobaia por volume; lara/select herdam
  selectors idênticos.

## Status do validador

`validation.json::passed_hard = true`. Fill rate = **24/25 = 96%**.

SOFT warnings (1):
- `address.cep ausente` — provider não publica CEP no detalhe nem
  no endereço de vistoria. Limitação documentada (aplicável aos 3
  tenants, presumivelmente a todo o provider).

Hard checks: title, source_lot_url (literal em `pilot_source.html`),
`address.raw_text`, `auction_status`, ≥1 round com `minimum_bid_brl`,
proveniência. Todos OK.

Tentativas até passar: **1**.
