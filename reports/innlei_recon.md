# Recon — innlei.org.br/leiloeiros

Data do recon: 2026-04-25
Responsável: descoberta automatizada (curl + python)

## TL;DR

A página `/leiloeiros` é uma SPA Next.js (App Router) que renderiza apenas um shell com "Carregando leiloeiros..."; a lista real é hidratada client-side via fetch a uma **API JSON pública**. Em vez de raspar HTML paginado e renderizar JS, basta consumir o endpoint REST diretamente.

- **Endpoint canônico**: `GET https://innlei.org.br/api/public/leiloeiros?page=N&limit=100`
- **Total de leiloeiros**: **2749** (em 25/04/2026)
- **Páginas necessárias com limit=100**: **28** (`totalPages` é informado na resposta)
- **Auth / CORS / cookies**: não há. Funciona via curl direto sem User-Agent específico.
- **Robots.txt**: não existe (`/robots.txt` → HTTP 404). A meta tag `noindex` aparece só na página 404. Sem proibição explícita à API; ainda assim vamos rodar 1 req/s.

## Stack do site

| Sinal | Valor |
| --- | --- |
| `x-powered-by` | `Next.js` |
| `x-nextjs-prerender` | `1` (página é prerenderizada estática) |
| `x-nextjs-cache` | `HIT` (Vercel/CDN edge cache) |
| Server | `cloudflare` |
| RSC payload | `self.__next_f.push([...])` (App Router, não Pages Router) |
| Tamanho do HTML | ~16 KB — apenas shell, zero conteúdo de leiloeiro |

A confirmação visual está no único texto humano dentro do `<body>`: "Carregando leiloeiros…". O HTML inicial **não** carrega `__NEXT_DATA__` com a lista — a página depende totalmente do fetch client-side.

## Endpoints descobertos

Extraídos do bundle `_next/static/chunks/app/leiloeiros/page-a4ce7d9f7db72173.js`:

| Endpoint | Uso |
| --- | --- |
| `GET /api/public/leiloeiros?page=N&limit=L` | Listagem paginada — **principal** |
| `GET /api/public/leiloeiros/{id}` | Perfil individual por **id numérico** (slug retorna 404) |
| `GET /api/public/juntas` | Lista das Juntas Comerciais estaduais |
| `GET /api/leiloeiro/matriculas` | (não investigado) |

### Paginação

A resposta da listagem inclui:

```json
{ "data": [...], "page": 1, "limit": 100, "total": 2749, "totalPages": 28 }
```

- `limit` aceita 1..100. Valores **acima de 100 são ignorados** e o servidor devolve o default `limit=20`. O cap real e silencioso é 100 — descoberto empiricamente (`limit=100` → 100 itens; `limit=150` → 20 itens).
- Sem `page` ou `limit`, default é `page=1, limit=20`.
- Plano: `limit=100`, `page=1..28`, com `1 req/s` → ~28 s no total.

### Schema dos itens (já vem completo na listagem)

Campos observados em `data[i]`:

```
id              int           ex.: 2023
nome            str           "Gelson Bourschiet"
slug            str           "gelson-bourschiet"  (não navegável: /leiloeiros/<slug> → 404)
email           str | ""
telefone        str           "(41)99683-1730"  ou  "(11)2925-8699 | (11)99241-8806"
celular         str
endereco        str           às vezes só rua, às vezes string única com tudo
cidade          str | ausente
cep             str | ausente
juntaComercial  str           "JUNTA COMERCIAL DO PARANA"
matricula       str           "23-379/L"
anoPosse        str           "24/08/2023"   (data de posse, formato dd/mm/yyyy)
matriculas      list[obj]     com {matricula, anoPosse, status, junta:{id,nome,sigla,uf}}
                              ⇒ é a fonte canônica de UF (ex.: "PR")
dadosJunta      obj           reflexo da Junta principal (parcialmente redundante)
situacao        str           "Regular" (todos os 20 da pág 1 estão Regular)
dominio         str           SITE EXTERNO do leiloeiro (chave que precisamos!)
dominio_url     str           subdomínio leilao.br (ex.: "shopleiloes.leilao.br")
dominio_status  str           "ativo" / outros
dominio_online  bool          health-check do INNLEI
dominio_leilao_br bool        usa o subdomínio leilao.br
imagem          str           foto do leiloeiro (S3)
facebook,
instagram,
linkedin,
youtube,
twitter,
tiktok          str | ausente   (tiktok só apareceu no perfil individual)
credenciamento  str           "credenciado" | ...
isAssociado     bool
nivel,nivelLabel str          "prata" / "Prata"   — nível do plano associativo
bairro,numero   str           SOMENTE no endpoint /{id}, não na listagem
```

### Ausência crítica

**Nenhum dos endpoints expõe "tipo de leilão" / "especialidade"** (imóveis vs veículos vs judicial vs rural). A única informação ligada ao tipo de atuação é:

- O nome de fantasia / razão social (ex.: "LeilóMinas", "Imobi-Leilões")
- O `dominio` (site externo) — é onde precisaremos olhar

⇒ A fase de **filtragem por imóveis** terá que se apoiar em heurísticas sobre o **conteúdo do site externo** (título, meta description, palavras-chave), não em metadados do INNLEI. O `enrich_auctioneers.py` precisa ser repensado: o "perfil INNLEI" não acrescenta praticamente nada à listagem (apenas `bairro`, `numero`, `tiktok`); o que de fato enriquece é visitar o próprio `dominio`.

## Plano de scraping

| Fase | Estratégia |
| --- | --- |
| **1. Descoberta (`innlei_scraper.py`)** | 28 GETs a `/api/public/leiloeiros?page=N&limit=100`. Salvar 1 linha CSV por leiloeiro com colunas: `id, slug, nome, email, telefone, celular, cep, cidade, uf (de matriculas[0].junta.sigla), endereco, dominio, dominio_url, dominio_online, situacao, credenciamento, isAssociado, juntaComercial, matricula, anoPosse, facebook, instagram, linkedin, youtube, url_perfil_innlei (`/leiloeiros/{slug}` apenas referência), imagem`. **Não há HTML para parsear** — só JSON. |
| **2. Enrich (`enrich_auctioneers.py`)** | Refocar: para cada leiloeiro com `dominio` não-vazio, GET no site externo, extrair `<title>`, `<meta name="description">`, palavras-chave do `<body>` (até N kB). Cache em disco por URL. Saída acrescenta colunas `site_title, site_description, site_keywords_blob, site_status_code`. |
| **3. Filter (`filter_real_estate.py`)** | Heurística sobre `nome` e blob do site: palavras `imóvel/imovel`, `imobil`, `apartamento`, `casa`, `terreno`, `lote`, `praça/praca`, `matrícula/matricula`, `judicial`, `extrajudicial`. Three-way confidence: `high` (palavras-chave fortes em título/meta), `medium` (palavras-chave fracas ou só no nome), `unknown` (sem sinal). |
| **4+. Scrapy** | A partir do CSV `auctioneers_real_estate.csv`, gerar um spider por leiloeiro de imóveis. |

## Ética e boas práticas

- API é pública e usada pelo próprio site para popular a lista — não há contorno de auth.
- Sem `robots.txt` proibitivo. Mesmo assim: 1 req/s, User-Agent identificável, parar imediatamente em 429/5xx.
- Dados pessoais expostos (email/telefone) já são publicados pelo INNLEI por mandato legal (transparência da atividade leiloeira). Tratar com cuidado mesmo assim — não publicar derivados sem propósito.

## Pendências para validar antes/durante o scrape

- [ ] Confirmar que `limit=100` é estável em todas as páginas (testado só na 1).
- [ ] Verificar se algum leiloeiro tem `situacao != "Regular"` (na pág. 1 todos eram Regular — pode haver "Suspenso", "Cancelado").
- [ ] Validar consistência da UF: usar `matriculas[0].junta.sigla` (curta, ex.: "PR") em vez de parsear `juntaComercial` (string longa).
- [ ] Decidir o que fazer quando `dominio` está vazio ou aponta para subdomínio `leilao.br` genérico vs site próprio.
