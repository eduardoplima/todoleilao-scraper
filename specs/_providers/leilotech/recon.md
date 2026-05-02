# leilotech (provider recon)

Provider multi-tenant que serve **18 leiloeiros** (cf. `_input.json`).
Tenant escolhido como representativo: **`topoleiloes.com.br`**
(GUILHERME EDUARDO STUTZ TOPOROSKI, SC). O recon é arquitetural — uma
spider parametrizada por `{base_url}` deve cobrir todos os tenants.

## Tech stack & rendering

- **Backend**: Laravel + **Livewire** (componentes server-rendered com
  estado serializado em `wire:snapshot="..."` no HTML inicial).
- **Frontend**: Tailwind, Alpine.js, FontAwesome, Turnstile (Cloudflare
  bot challenge — só em formulários, não bloqueia GET anônimo).
- **CDN**: `cdn.leilotech.workers.dev` (Cloudflare Workers + R2 ou
  similar). Assinatura única do provider, presente em **todos** os
  tenants probados (alleiloes, spencerleiloes, vasconcelosleiloes,
  oleiloes — confirmado).
- **Edge**: `server: cloudflare` em todos os tenants.
- **Rendering**: **estático** com payload completo embutido. O HTML
  inicial **já contém** o lote inteiro como JSON dentro do
  `wire:snapshot` (≈ 36 KB de JSON entity-encoded). Nenhum XHR
  necessário para o detalhe. `requires_playwright = False`.

### Como ler o snapshot no spider

```python
import re, html, json
m = re.search(r'wire:snapshot="([^"]{1000,})"', detail_html)  # o maior é o lote
data = json.loads(html.unescape(m.group(1)))
lote = data["data"]["lote"][0]
# lote keys: id, slug, title, leilao, leilao_id, table_rows, status_banner,
#            description_html, info_adicional_html, images, documents,
#            actions, ...
```

`table_rows` é uma lista de pares `[obj, {"s":"arr"}]` (encoding interno
do Livewire). Filtre `row[0]["label"] / row[0]["value"]`. Veja
`build_pilot.py` neste diretório como referência.

## Listing ativa

- **URL**: `https://{tenant}/` (a home **é** a listagem ativa).
- **Card selector**: `a[href*='/lote/']` (mistos imóveis + veículos +
  outros). Filtragem por `PROPERTY_CATEGORY_RE` no anchor text.
- **Paginação**: `none` na primeira inspeção. A home lista todos os
  lotes ativos atuais (29 anchors úteis em `topoleiloes`). Se algum
  tenant ultrapassar o threshold, há provavelmente paginação por
  rolagem ou `?page=N` — checar caso a caso quando rodar a spider.
- **Categoria**: o anchor text já carrega tipo e desconto
  (`Sobrado·\n 350,00m² AT`, `Apartamento·\n Á. Privativa 49,49`).

## Listing encerrada

- **URL**: `https://{tenant}/encerrados` — rota canônica do provider.
  HTTP 200; mesmo template da home, anchors `/lote/{id}/{slug}` com
  badge "LOTE vendido", "LOTE sem licitante", "LOTE suspenso", etc.
- **Schema**: idêntico à listagem ativa (mesmo `card_selector`).
- **Mistura veículos/imóveis** igual à home.
- **Paginação**: `none` no índice testado (5 leilões agrupados,
  ~19 anchors). Volume crescente exigirá investigação caso a caso.

## Pilot lot escolhido

- **Lote**: `33128` — "Apartamento com vaga - Ed. Independência -
  Av. Dom Pedro I, 219 - Cambuci - São Paulo/SP".
- **URL**: `https://topoleiloes.com.br/lote/33128/apartamento-com-vaga-ed-independencia-av-dom-pedro-i-219-cambuci-sao-paulosp`
- **Status**: `arrematado` (banner `bg-green-600` "VENDIDO").
- **Avaliação**: R$ 470.700,91. **Vendido por**: R$ 318.420,55.
  Total de 17 lances. Apelido vencedor: `THE BIG`.
- **Rounds**: 2 leilões com data + lance inicial (470.700,91 e
  282.420,55). 2º arrematado.
- **Fill rate**: 23/25 = 92%. SOFT warnings: `bids` (não exposto,
  abaixo) e `encumbrances_raw` (não há campo dedicado; texto livre
  na descrição).

### Bids: NÃO expostos

O snapshot inclui apenas **agregados**:
`Maior Lance: R$ 318.420,55`, `Apelido: THE BIG`, `Total de lances: 17`.
Não há `historico`, `lances`, ou endpoint paralelo (`/lote/{id}/lances`,
`/api/...` retornam 404 ou redirecionam pra mesma página). Conforme
`closed-auction-bids` skill §5, registramos `bids: []` e movemos o
resultado bruto para `rounds[-1].status_raw`. O spider de produção
NÃO deve tentar pescar lances individuais — eles não existem
publicamente neste provider.

## Gotchas

- **Slug canônico inclui UF colada** (`...-sao-paulosp`, não `-sao-paulo-sp`).
  O servidor aceita variações mas só a versão canônica casa o teste de
  proveniência (URL literal no HTML). Sempre seguir `lote.canonical`
  quando disponível.
- **`description_html` decoded com cuidado** — entities duplas
  (`&amp;ordm;`, `&amp;sup2;`) aparecem porque o snapshot já é
  entity-encoded uma vez (HTML attribute) e o conteúdo `description_html`
  **também** chega entity-encoded. `html.unescape` cobre as duas
  camadas se for chamado uma vez por nivel.
- **`Lance inicial:` é HTML composto** com vários `<span>` empilhados
  (1º leilão, 2º leilão, "vendido por"). Strip tags antes de regex.
- **Categoria no slug é confiável** (apartamento-com-vaga-ed-...);
  `lote.categoria_nome` e `lote.categoria_id` chegaram **null** — não
  confiar neles.
- **Documentos vêm em duas estruturas**: `lote.documents[]` (Avaliação,
  Matrícula — em `cdn.leilotech.workers.dev`) e `lote.actions[]`
  (label "EDITAL", URL `/{publicacao_id}/publicacao` no domínio do
  tenant). Coletar de ambos.
- **PII**: descrição **não traz CPF nem nome PF**. `Apelido` é handle
  pseudonimizado por design ("THE BIG") — mantemos como está
  (apelido é dado público em contexto de leilão).
- **`leilao_id` ≠ `lote_id`**: snapshot expõe `lote.leilao_id` (id do
  edital agrupado). Útil para listing por leilão se quiser
  paginação/agrupamento.

## Decisões e limitações

1. **Spider único parametrizado por `{base_url}`** cobrirá os 18 tenants
   sem código duplicado. Plataforma = `leilotech-livewire`.
   `requires_playwright = False`.
2. **bids = `[]` por design** (provider não publica). Documentado
   acima; spider de produção não deve gastar requests caçando o que
   não existe.
3. **Paginação só será descoberta empiricamente** quando algum tenant
   exibir > 1 página de listagem. Por ora, `kind: none`.
4. **Rate limit**: 1.5 s respeitado em todas as requisições do recon.
   `robots.txt`: `Disallow:` (sem restrições).
5. **`build_pilot.py`** ficou no diretório como **referência** do
   parser do snapshot — quando o spider for escrito, transplantar a
   lógica regex de `Lance inicial`, `LOCALIZAÇÃO:`, e o coletor
   recursivo de `images`/`documents`/`actions`.

## Arquivos

- `pilot_listing.html` — `/encerrados` de topoleiloes (Etapa 3/4).
- `pilot_source.html` — detalhe do lote 33128.
- `snapshot_0.json` — wire:snapshot decodado (lote completo). Ficou no
  disco como artefato de recon; não é necessário em produção (extrair
  on-the-fly do HTML).
- `pilot_item.json` + `validation.json` — resultado validado.
- `build_pilot.py` — script de extração; serve de blueprint para o
  parser final.
