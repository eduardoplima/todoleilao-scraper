# degrau_publicidade

Recon arquitetural do provider **Degrau Publicidade e Internet**, marca
"Sua Plataforma de Leilão" (`https://www.suaplataformadeleilao.com.br/`).
Provider multi-tenant: hospeda leilões para 26 leiloeiros distintos, cada
um com seu próprio domínio (casareisleiloes, amazonasleiloes,
milhaoleiloes, suporteleiloes, robotton — comitente, etc.) mas todos
servidos pelo mesmo bundle `/Core/V1/*` e mesmas rotas `/ApiEngine/*`.

Site representativo escolhido: **Casa Reis Leilões Online**
(`https://www.casareisleiloes.com.br/`), leiloeiros oficiais Eduardo dos
Reis e Roberto dos Reis Junior (JUCESP, SP).

## Tech stack & rendering

`site_analysis.csv` traz: `tech_stack=jQuery; Bootstrap`,
`tech_signals=jquery | bootstrap | server:cloudflare`,
`rendering=dynamic`, `requires_js_for_listings=False` (esse último é
resíduo da heurística — a listagem é dinâmica de fato; o que está
estático é só meia dúzia de banners de destaque na home). Confirmado.

- **Frontend SPA-hash + jQuery templates** (`jquery-tmpl`,
  `TrimPath.processDOMTemplate`). A "listagem" `/busca/` lê parâmetros
  de `window.location.hash` (`#Engine=Start&Pagina=N&SubStatus=...`),
  monta um payload e dispara `POST /ApiEngine/GetBusca/`. O HTML
  inicial não tem nenhum card — só banners de destaque (16 anchors
  estáticos para `/lote/...`, mas são curadoria editorial, não
  listagem). Real-time updates via SignalR
  (`/Core/V1/js/signalr/dist/browser/signalr.js` + ConnectionHubs).
- **Backend ASP.NET-style** com endpoints `/ApiEngine/*` retornando
  JSON. Todos os domínios do provider expõem o mesmo conjunto de
  rotas (verificado também em amazonasleiloes.com.br): listagem
  multi-tenant é roteada por `Host` + `ID_Cliente` server-side.
- **CDN Cloudflare** na frente (`server: cloudflare`). Imagens e PDFs
  são servidos pelo próprio domínio do leiloeiro (`/imagens/...`,
  `/preview/...`) — não há CDN externo separado como em SOLEON.
- **Plataforma marker**: `<meta name="plataforma_de_leilão:nome"
  content="Sua Plataforma de Leilão | Degrau Publicidade e Internet">`
  no `<head>` + link no rodapé para `suaplataformadeleilao.com.br`.
  Bundle `Core/V1/*` é o cookie técnico definitivo.
- **robots.txt**: apenas comentário sobre content-signals (search,
  ai-input, ai-train) — sem cláusulas `Disallow` ativas. Acesso livre
  a todos os paths públicos. `TodoLeilaoBot/1.0` permanecido como UA;
  rate-limit ≥1.5s respeitado em todos os fetches (1 home + 1 robots
  + 4 JS bundles + 1 GetBusca + 1 detail + 1 GetLancesPropostas = 9
  requests, ~13.5s de delay total).

**Conclusão**: `requires_playwright = False`. Toda Fase 1 e Fase 2
podem rodar com `httpx` puro chamando `/ApiEngine/GetBusca` e
`/ApiEngine/GetLancesPropostasLote` diretamente. Playwright fica
reservado eventualmente para captura de novos endpoints.

## XHRs descobertas

Todos sem auth, content-type `application/json; charset=utf-8`,
header recomendado `X-Requested-With: XMLHttpRequest`:

| Método | URL                                                                | Body                                         | Resposta                              |
|--------|--------------------------------------------------------------------|----------------------------------------------|---------------------------------------|
| POST   | `/ApiEngine/GetBusca/{Pagina}/{PaginaIndex}/{IndexOut}`             | filtros (SubStatus, ID_Categoria, ID_Estado…) | `{Lotes:[…], Paginacao, CountTotal, CountEncerrado, …}` |
| POST   | `/ApiEngine/GetLotes/{Pagina}/{QtdPorPagina}`                       | filtros (uso interno em painel/comitente)    | `{Lotes:[…], CountTotal, …}`         |
| POST   | `/ApiEngine/GetLancesPropostasLote/{ID_Leilao}/{ID_Leiloes_Lote}`   | `{}`                                         | `{Lances:[…], Propostas:[…]}`         |
| POST   | `/ApiEngine/GetLancesLote/{ID_Leilao}/{ID_Leiloes_Lote}`            | `{}`                                         | versão modal de Lances (idem)        |
| POST   | `/ApiEngine/GetRealTime`                                            | `{IDsLotes:[…]}`                             | atualização SignalR de praça/lance   |
| POST   | `/ApiEngine/GetLotesSuperDestaque/{Pagina}`                         | `{UF: "..."}`                                | banners home                          |
| POST   | `/ApiEngine/GetLeiloesDestaqueV2/{Pagina}/{PaginaIndex}/{IndexOut}` | filtros                                      | leilões agrupados (não lotes)        |

`/ApiEngine/GetLotes/` ignora silenciosamente `IDs_Leiloes_Status` e
`SubStatus` (sempre devolve a mesma lista) — usar **sempre**
`/ApiEngine/GetBusca/` para qualquer filtragem real.

### Mapa de status canônico (do bundle `Ajax_Leiloes.js` linha 7505)

```
ID_Leiloes_Lotes_SubStatus:
  1 = Online            (ativo / aberto para lance)
  2 = Suspenso
  3 = Prejudicado
  4 = Encerrado         (terminou sem arrematação)
  5 = Arrematado
  6 = Aguardando
  7 = Aguardando Datas
  8 = Aberto
  9 = Venda
  10 = Condicional
  11 = Dou-lhe uma
  12 = Dou-lhe duas
  13 = Dou-lhe três
  14 = Homologar
  15 = Repasse
```

`idsENCERRADOS = [2, 3, 4, 5, 10, 15]` na lógica do front. Para o
Pilot do encerrado prefiro `[4, 5]` (estritamente terminados).

## Listing ativa

URL canônica de UI:
`/busca/#Engine=Start&Pagina=1&Busca=&Mapa=&ID_Categoria=1&SubStatus=1,8`
(filtra IMÓVEIS abertos). Sem fragment, `/busca/` mostra todos os
status.

Fonte de dados real: `POST /ApiEngine/GetBusca/{page}/1/0` com payload
mínimo `{"SubStatus":[1,8],"ID_Categoria":1,"QtdPorPagina":24,"Pagina":1}`.
Retorna 142 lotes totais no momento do recon (mas a maioria está
"Aguardando datas"). Paginação via `body.Pagina` (incrementa) +
`response.PageIndexMax`.

`card_selector` em SPA é academicamente "`a[href*='/lote/']`", mas o
spider real **vai bater na API**: `response.Lotes[].URLlote` já é o
slug `lote/{slug}/{id}/` que basta concatenar com o domínio.

## Listing encerrada

URL canônica de UI:
`/busca/#Engine=Start&Pagina=1&Busca=&Mapa=&ID_Categoria=1&SubStatus=4,5`.

`POST /ApiEngine/GetBusca/1/1/0` com body
`{"SubStatus":[4,5],"ID_Categoria":1,"QtdPorPagina":24,"Pagina":1,"PaginaIndex":1}`
retornou `CountTotal=43`, `PageIndexMax=3`, com 8 lotes na página 1
todos com `ID_Leiloes_Lotes_SubStatus ∈ {4, 5}`. Spider de produção
deve paginar até esgotar.

Filtragem por categoria de imóvel: `ID_Categoria=1` cobre o macro
"IMÓVEIS"; subcategorias (apartamento=3, casa, terreno=12,
comercial...) ficam em `ID_Categoria_Lote` no response. Recomendo
filtrar `ID_Categoria=1` no request e refinar por
`Lote.ID_Categoria_Lote` localmente — evita perder lotes mistos.

## Pilot lot escolhido

URL: `https://www.casareisleiloes.com.br/lote/terreno-no-altavis-aldeia-santana-de-parnaiba/4580/`

Leilão: `/leilao/terreno-no-altavis-aldeia-santana-de-parnaiba/3385/`
(CodLeilao 8475, modalidade Judicial, comitente E.TJ-SP, processo
0001003-86.2022.8.26.0529).

Motivo da escolha: dos 43 encerrados/arrematados disponíveis no
filtro `SubStatus=[4,5]`, este lote tinha **27 lances reais e
disputa real** (paulochagas vs felipemacedo + acmpc cruzando lances
em ~50 minutos no dia 19/03/2026), arrematado a R$ 462.947,59
(72,5% da avaliação atualizada de R$ 645.895). Cobre o eixo
`bids:sim` do recon de encerrados sem ambiguidade. O segundo melhor
candidato (lote 4453, Apê Morumbi) tinha apenas 1 lance.

| Campo                | Fonte / Seletor                                                     | Valor (resumido)                            |
|----------------------|---------------------------------------------------------------------|---------------------------------------------|
| title                | `h1.dg-lote-titulo` (server-side) + `Lote` da API                   | "Terreno - Estrada Mun. Mascarenhas de Moraes, 5.800, Santana de Parnaíba" |
| description          | `section#dg-lote-descricao .dg-lote-descricao-txt` (HTML do edital) | 1.4 KB de prosa (vide pilot_item.json)      |
| property_type        | `Lote.ID_Categoria_Lote = 12 → terreno`                              | `terreno`                                   |
| address.raw_text     | `section#dg-lote-local .dg-lote-local-endereco` + Lote_CEP da API   | "Estrada ..., 5800 - Sítio do Morro - Santana de Parnaíba - SP - CEP: 06517-520" |
| address.cep          | `Lote.Lote_CEP`                                                     | `06517-520`                                 |
| address.uf           | `Lote.UF`                                                           | `SP`                                        |
| address.municipality_name | `Lote.Cidade`                                                  | `Santana de Parnaíba`                       |
| total_area_sqm       | regex `Á?REA DO TERRENO`/`509,73m²` no card de configs              | `509.73`                                    |
| market_value_brl     | `Lote.ValorAvaliacao` (638333.33 — original do edital)              | `638333.33`                                 |
| rounds[1].minimum_bid_brl | `GetLoteRealTime[0].ValorMinimoLancePrimeiraPraca`             | `322947.59`                                 |
| rounds[1].scheduled_at | `GetLoteRealTime[0].DataHoraAberturaPrimeiraPracaFormat` + BRT    | `2025-12-19T13:00:00-03:00`                 |
| auction_status       | `GetLoteRealTime[0].ID_Leiloes_Lotes_SubStatus = 5 → arrematado`    | `arrematado`                                |
| images               | `a.jsLoteImgItem[href*='/imagens/1300x1300/']` (server-side)        | 27 únicas                                   |
| documents            | `ul.jsLoteAnexos a[href*='/preview/'][href$='.pdf']`                | 9 docs (edital, matrícula, laudo, IPTU…)    |
| bids                 | `POST /ApiEngine/GetLancesPropostasLote/3385/4580` → `Lances[]`     | 27 lances (todos válidos, IsRecusado=0)     |
| encumbrances_raw     | parse manual da `description` (HTML do edital)                       | 5 cláusulas (hipoteca, penhora, posse, IPTU, taxa associativa) |

## Gotchas

1. **A listagem ativa só responde via API.** Tentar parsear o HTML
   `/busca/` é zero — o conteúdo é injetado pelo `TrimPath` em
   `#TemplaGetLeiloesDestaque`/`TemplaResultadoLotesBusca`. Spider
   tem que falar `application/json` direto com `/ApiEngine/GetBusca/`.

2. **SubStatus filtering é por `GetBusca`, não `GetLotes`**. Bati o
   `/ApiEngine/GetLotes/` com `{ID_Leiloes_Status:3}` e ele ignorou
   silenciosamente — devolveu a mesma lista que `{}`. `GetLotes/` é
   o endpoint público de "tudo o que existe" sem filtros de status;
   `GetBusca/` é o que respeita o vetor `SubStatus[]`.

3. **`SubStatus` vs `ID_Leiloes_Lotes_SubStatus`**. O front usa o
   nome curto na request; a chave longa aparece na response (em
   `Lote.GetLoteRealTime[0].ID_Leiloes_Lotes_SubStatus`). Mapa:
   1=Online, 4=Encerrado, 5=Arrematado (vide tabela acima).

4. **Praças únicas vs múltiplas.** Este pilot é `QtdPracas=1`
   ("Praça Única" — Hastas Públicas). Outros lotes do mesmo provider
   têm 2 praças (1ª e 2ª) e até 3ª (extrajudicial alienação
   fiduciária). Spider deve ler `GetLoteRealTime[0].QtdPracas` e
   emitir N rounds com seus pares
   `DataHoraAberturaXxxPracaFormat` + `ValorMinimoLanceXxxPraca`.

5. **`ValorAvaliacao` ≠ `GetValorAvaliacao`**. Original do edital
   (R$ 638.333,33) vs atualizado/corrigido (R$ 645.895,18 com data
   FEV/26). O edital sempre cita o original; a API serve os dois.
   Em `market_value_brl` mantive o original (mais estável e o que
   o juiz fixou).

6. **Datas sem timezone na API.** Todos os `DataHora*Format` vêm
   como string ISO sem TZ (`"2026-03-19T13:00:00"`). Servidor está
   em SP; assumo `-03:00` (BRT). Lances também: `DataHoraLance`
   `"2026-03-19T13:02:27.307"` — appendar `-03:00`.

7. **Apelidos de bidders ≠ PII**. Dos 27 lances: paulochagas,
   felipemacedo, acmpc — todos são handles públicos do auditório do
   provider; não há CPF nem nome PF expostos. O endpoint
   `/ApiEngine/GetLancesPropostasLote/` traz `IP` do bidder (`201.46.28.20`)
   que **não copio** para `bidder_raw` (PII de rede). Mantenho só
   `Apelido`.

8. **Lance recusado.** Campo `IsRecusado` nos `Lances` indica se o
   sistema rejeitou o lance (e `RecusadoMotivo` carrega texto). Spider
   filtra `IsRecusado > 0` antes de entrar em `bids[]` — esse pilot não
   tem nenhum, mas a regra fica documentada.

9. **Imagens em formatos mistos**. Mesmo lote tem `.jpg`, `.jpeg` e
   `.png` no mesmo carousel (`jsLoteImgItens`). Filtro deve aceitar
   todos. Padrão: `/imagens/1300x1300/{guid}.{ext}` (full size para
   preview/lightbox; `/imagens-complete/605x487/` é o thumbnail
   inline; `/imagens-center/770x620/` é o intermediário). Salvar
   apenas a 1300x1300 (canônica de maior resolução).

10. **Documentos com `kind=outro`**. Provider rotula PDFs com nomes
    livres ("Considerações", "Lote", "IPTU", "Débito Condominial").
    Mapeei o que casou com o vocabulário (`matricula`, `laudo`,
    `edital`, `certidao`); o resto vai como `outro`. Spider de produção
    pode refinar via heurística no nome do PDF.

11. **Multi-tenant: detecção da plataforma no spider.**
    Heurística mais robusta:
    `<meta name="plataforma_de_leilão:nome" content="Sua Plataforma de Leilão | Degrau Publicidade e Internet">`
    (case-sensitive). Fallback: link `suaplataformadeleilao.com.br`
    no rodapé OU bundle `/Core/V1/js/Ajax/Ajax_Leiloes.js`.

12. **PII verificada (PLANOMESTRE §4)**.
    - **CPF**: nenhum no `description`, `address.raw_text`, ou
      `bidder_raw` deste pilot. Edital cita só CNPJ
      (08.405.960/0001-43 — Nova Aldeia, PJ → mantido).
    - **Nome PF**: nenhum identificável neste pilot.
    - **Comitente**: E.TJ-SP (agente público) → mantido.
    - **Bidders**: 3 apelidos públicos, sem PII → mantidos.
    Anotação em `parser_notes`: *"sem PII a redigir"*. Outros lotes do
    provider (judiciais com `Reu`/`Autor` preenchidos) podem trazer
    nomes PF — Fase 2 pseudonimiza ao copiar para `description`.

## Decisões e limitações

- **`platform_hint = "degrau_publicidade"`** (canônico do provider).
- **`requires_playwright = False`**: toda listagem e bid history
  acessível via XHR JSON puro.
- **`listing_active.url_pattern`**: `/busca/#...&SubStatus=1,8`
  (anchor é a UI; spider chama API).
- **`listing_closed.url_pattern`**: `/busca/#...&SubStatus=4,5`.
- **Pilot `auction_status = arrematado`**: alvo do recon. 27 lances
  capturados, todos públicos. Vencedor `paulochagas` a R$ 462.947,59.
- **`market_value_brl = 638333.33`** (avaliação original do edital,
  set/2025) — o `GetValorAvaliacao` (645895.18 atualizado FEV/26) é
  cosmético.
- **Único `round_number = 1`** (Praça Única / Hastas Públicas) —
  `QtdPracas=1` na API. `status_raw` carrega o resumo legível
  ("Arrematado por R$ ... em 19/03/2026 13:02 (paulochagas)").
- **`area_sqm = null`** deliberado (terreno; toda a métrica disponível
  é o total 509,73m²).
- **Rate limit ≥1.5s** mantido. Total: 9 requests (~13.5s delay).
- **Sem Playwright/HAR** — não foi necessário; toda recon foi `curl`
  + leitura dos JS bundles.

## Status do validador

`validation.json::passed_hard = true`, **0 SOFT warnings**. 24 dos 25
campos checados de fill-rate preenchidos; apenas `area_sqm` ficou em
zero, justificado acima (terreno sem distinção área útil/construída).
Validador passou na **1ª tentativa**.
