"""Spider para tenants do provider SOLEON.

SOLEON (Soluções para Leilões Online) é multi-tenant: 116 leiloeiros
brasileiros usam a mesma stack Bootstrap 4 + jQuery sobre PHP. Selectors
em `specs/_providers/soleon/selectors.yaml`.

Fluxo (3 níveis):
    1. home (= listing_active) → cards `a[href*='/leilao/'][href$='/lotes']`
    2. /leilao/{id}/lotes → cards `a[href*='/item/'][href$='/detalhes']`
    3. /item/{lot_id}/detalhes → PropertyItem

Uso:
    scrapy crawl soleon                       # 1 site (representante)
    scrapy crawl soleon -a sites=5            # top 5 SOLEON
    scrapy crawl soleon -a sites=all          # 116 sites
    scrapy crawl soleon -a urls=https://...   # URL específica
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

import scrapy

from leilao_scraper.spiders._provider_base import ProviderSpider


class SoleonSpider(ProviderSpider):
    name = "soleon"
    provider_slug = "soleon"
    auctioneer_slug = "soleon"  # placeholder; sobrescrito por host na extração
    requires_playwright = False

    custom_settings = {
        # SOLEON é estático mas tem 116 tenants — limita pra evitar tempestade
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
    }

    LEILAO_LOTES_HREF_RE = re.compile(r"/leilao/\d+/lotes/?(?:\?|$)")
    ITEM_DETALHES_HREF_RE = re.compile(r"/item/\d+/detalhes/?(?:\?|$)")

    # ------------------------------------------------------------------
    # Nível 1: home → /leilao/{id}/lotes
    # ------------------------------------------------------------------
    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        sel = self.selectors["listing_active"]["card_selector"]
        seen: set[str] = set()
        for href in response.css(f"{sel}::attr(href)").getall():
            if not href or not self.LEILAO_LOTES_HREF_RE.search(href):
                continue
            absolute = response.urljoin(href)
            if absolute in seen:
                continue
            seen.add(absolute)
            yield self.make_request(
                absolute,
                callback=self.parse_leilao_lotes,
                meta={"source_listing_url": response.url},
            )
        self.log_event(
            "soleon_home_done",
            host=self.host_of(response.url),
            leilao_links=len(seen),
        )

    # ------------------------------------------------------------------
    # Nível 2: /leilao/{id}/lotes → /item/{lot_id}/detalhes
    # ------------------------------------------------------------------
    def parse_leilao_lotes(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        # Cláusulas gerais do leilão (regras de pagamento + ônus declarados).
        # Aplicadas a todos os lotes deste leilão e propagadas via meta.
        # O parser do detail pode adicionar cláusulas específicas do lote.
        page_text = _normalize_text(" ".join(response.css("body *::text").getall()))
        payment_options, encumbrances = _parse_auction_clauses(page_text)
        self.log_event(
            "soleon_leilao_clauses",
            url=response.url,
            payments=[p["kind"] for p in payment_options],
            encumbrances=[e["kind"] for e in encumbrances],
        )

        seen: set[str] = set()
        kept = 0
        dropped_non_imovel = 0
        ambiguous = 0
        for card in response.css("div.lote"):
            href = card.css("a[href*='/item/']::attr(href)").get()
            if not href or not self.ITEM_DETALHES_HREF_RE.search(href):
                continue
            absolute = response.urljoin(href)
            if absolute in seen:
                continue
            seen.add(absolute)
            verdict = _card_category(card)
            if verdict is False:
                dropped_non_imovel += 1
                continue
            if verdict is None:
                ambiguous += 1
            kept += 1
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={
                    "source_listing_url": response.url,
                    "category_verdict_listing": verdict,  # True | None (ambíguo)
                    "auction_payment_options": payment_options,
                    "auction_encumbrances": encumbrances,
                },
            )
        self.log_event(
            "soleon_leilao_lotes_done",
            url=response.url,
            lote_links=len(seen),
            kept=kept,
            dropped_non_imovel=dropped_non_imovel,
            ambiguous=ambiguous,
        )

    # ------------------------------------------------------------------
    # Nível 3: /item/{lot_id}/detalhes → PropertyItem
    # ------------------------------------------------------------------
    def parse_property(self, response: scrapy.http.Response):
        # Rede de segurança no detalhe: classifica via og:title + og:description
        # com lista positiva (deve ter sinal forte de imóvel) + negativa
        # (rejeita bens móveis). Estrito por design — vide _detail_is_imovel.
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""
        og_title = response.css("meta[property='og:title']::attr(content)").get() or ""
        if not _detail_is_imovel(og_title, og_desc):
            self.log_event(
                "soleon_lote_dropped_non_imovel",
                url=response.url,
                og_title=og_title[:60],
                og_desc=og_desc[:80],
            )
            return

        loader = self.new_loader(response)
        # auctioneer override: usa host como discriminador entre os 116 tenants
        host = self.host_of(response.url)
        loader.replace_value("auctioneer", f"soleon::{host}")

        # title — meta description: "Lote 001 - {TÍTULO} (ID {lot_id})"
        meta_desc = (
            response.css("meta[name='description']::attr(content)").get()
            or response.css("meta[property='og:title']::attr(content)").get()
            or ""
        )
        og_title = response.css("meta[property='og:title']::attr(content)").get() or ""
        loader.add_value("title", meta_desc)

        # lot_number — extrai "001" de "Lote 001 - ..."
        m_lot = re.match(r"\s*Lote\s+(\d+)", meta_desc, re.I)
        if m_lot:
            loader.add_value("lot_number", m_lot.group(1))

        # status — div.label_lote class names: aberto_lance, sem_licitante,
        # vendido, sustado
        label_classes = response.css("div.label_lote::attr(class)").get() or ""
        loader.add_value("status", _map_status(label_classes))

        # minimum_bid / market_value — preferir h6 (template "judicial");
        # fallback para og:title (template "venda direta", padronizado pelo SOLEON
        # em todos tenants: "<localização> - Lance Inicial: R$X- Avaliação: R$Y").
        price_min = _extract_brl_after_label(response, ["Lance Inicial", "Lance Mínimo"])
        if price_min is None:
            price_min = _extract_brl_from_og_title(og_title, "Lance Inicial")
        loader.add_value("minimum_bid", price_min)
        price_market = _extract_brl_after_label(response, ["Valor de Avaliação", "Avaliação"])
        if price_market is None:
            price_market = _extract_brl_from_og_title(og_title, "Avaliação")
        loader.add_value("market_value", price_market)

        # data — h6 com "Encerramento" (judicial) OU "Envie sua proposta até"
        # (venda direta). Fallback: og:description "Leilão: DD/MM/YYYY HH:MM"
        # Passa string BR para o ItemLoader (parse_br_date no input_processor).
        br_dt_text = _text_after_label(
            response,
            ["Encerramento", "Encerramento do Leilão", "Envie sua proposta até"],
        )
        if not br_dt_text:
            og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""
            m_dt = re.search(r"(\d{2}/\d{2}/\d{4}[^,]*\d{2}:\d{2})", og_desc)
            if m_dt:
                br_dt_text = m_dt.group(1)
        if br_dt_text:
            # Single-round: trata como segunda praça (judicial padrão SOLEON)
            loader.add_value("second_auction_date", br_dt_text)
            loader.add_value("auction_phase", "2a_praca")

        # description — `<div><b>Descrição: </b>texto livre do anúncio</div>`.
        # XPath cirúrgico: pega só o div cujo filho <b> começa com 'Descrição',
        # evitando incluir a UI inteira que o ":contains()" CSS pegaria.
        desc_nodes = response.xpath(
            "//div[b[starts-with(normalize-space(), 'Descrição')]]"
        )
        if desc_nodes:
            raw = " ".join(desc_nodes[0].css("*::text").getall())
            desc = re.sub(r"\s+", " ", raw).strip()
            desc = re.sub(r"^\s*Descri[çc][aã]o:\s*", "", desc, count=1)
            if desc:
                loader.add_value("description", desc[:10000])

        # address — h5 "Localização do Imóvel" + irmão div
        address_text = " ".join(
            response.xpath(
                "//h5[contains(., 'Localiza')]/following-sibling::div[1]//text()"
            ).getall()
        ).strip()
        if address_text:
            loader.add_value("address", _parse_address(address_text))

        # images — SOLEON usa carousel-item com style="background: url(...)";
        # path varia: /bens/, /watermark/bens/, ou domínio cloudfront/gocache
        # diretamente. Pegamos URL via regex em todo HTML do carousel + og:image.
        img_urls: list[str] = []
        carousel_html = " ".join(response.css("div.carousel-item").getall())
        img_urls.extend(_IMG_BENS_RE.findall(carousel_html))
        og_img = response.css("meta[property='og:image']::attr(content)").get()
        if og_img:
            img_urls.append(og_img)
        # Dedup preservando ordem
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            absolute = response.urljoin(u)
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs)

        # documents — pdf links no .arquivos-lote
        docs: list[dict] = []
        for a in response.css("div.arquivos-lote a[href$='.pdf']"):
            url = a.css("::attr(href)").get()
            label = " ".join(a.css("::text").getall()).strip() or None
            if url:
                docs.append({"name": label or "documento", "url": response.urljoin(url)})
        if docs:
            loader.add_value("documents", docs)

        # bids — div.ult_body div.ultimos-lances-item (server-side)
        bids = _extract_bids(response)
        if bids:
            loader.add_value("bids", bids)

        # Cláusulas: começa com as gerais do leilão (vindas via meta), e
        # mescla com sinais específicos extraídos do próprio detail.
        payment_options = list(response.meta.get("auction_payment_options") or [])
        encumbrances = list(response.meta.get("auction_encumbrances") or [])
        detail_text = _normalize_text(" ".join(response.css("body *::text").getall()))
        detail_pay, detail_enc = _parse_auction_clauses(detail_text)
        payment_options = _dedup_clauses(payment_options + detail_pay, key="kind")
        encumbrances = _dedup_clauses(encumbrances + detail_enc, key="kind")
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        # source_lot_code — extrai do path /item/{id}/detalhes
        m = re.search(r"/item/(\d+)/detalhes", response.url)
        if m:
            loader.add_value("source_lot_code", m.group(1))

        # scraped_at
        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "soleon_lote_extracted",
            url=response.url,
            host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            scheduled=item.get("second_auction_date"),
            imgs=len(item.get("images") or []),
            bids=len(item.get("bids") or []),
        )

        # Tenta enriquecer com cláusulas do PDF do edital antes de yield.
        # IMPORTANTE: yield só ocorre depois do callback do PDF (ou
        # imediatamente, se sem edital). DeduplicationPipeline descartaria
        # o item enriquecido se item HTML fosse yielded primeiro com a
        # mesma url. errback re-yielda item HTML em caso de PDF falho.
        edital_url = _find_edital_url(item)
        self.log_event(
            "soleon_edital_dispatch",
            url=response.url,
            edital_url=edital_url,
            n_documents=len(item.get("documents") or []),
        )
        if not edital_url:
            yield item
            return
        # `dont_obey_robotstxt`: CDNs (CloudFront, gocache) servem com
        # robots.txt default `Disallow: /`. Editais são publicidade
        # obrigatória por lei (LAI; CPC arts. 887, 889) e o leiloeiro já
        # linka pro PDF na página pública — exceção documentada ao
        # princípio ROBOTSTXT_OBEY do CLAUDE.md, restrita a PDFs de edital.
        yield self.make_request(
            edital_url,
            callback=self._merge_edital_clauses,
            cb_kwargs={"item_html": item},
            errback=self._on_edital_error,
            meta={
                "handle_httpstatus_list": [403, 404],
                "dont_obey_robotstxt": True,
            },
        )

    def _on_edital_error(self, failure):
        """Falha no download do PDF — yielda item HTML mesmo assim para não perder o lote."""
        self.logger.warning(
            f"edital download failed: {failure.request.url} — {failure.value!r}"
        )
        item_html = failure.request.cb_kwargs.get("item_html")
        if item_html is not None:
            yield item_html

    def _merge_edital_clauses(self, response: scrapy.http.Response, item_html):
        """Baixa PDF do edital, parseia e yielda item enriquecido (ou HTML cru)."""
        if response.status >= 400:
            yield item_html
            return
        cache = getattr(self, "_edital_cache", None)
        if cache is None:
            cache = self._edital_cache = {}
        if response.url in cache:
            pdf_pay, pdf_enc = cache[response.url]
        else:
            try:
                text = _pdf_to_text(response.body)
            except Exception as e:
                self.logger.warning(f"PDF parse failed {response.url}: {e}")
                cache[response.url] = ([], [])
                yield item_html
                return
            pdf_pay, pdf_enc = _parse_auction_clauses(text) if text else ([], [])
            cache[response.url] = (pdf_pay, pdf_enc)
            self.log_event(
                "soleon_edital_parsed",
                url=response.url,
                payments=[p["kind"] for p in pdf_pay],
                encumbrances=[e["kind"] for e in pdf_enc],
            )
        if not pdf_pay and not pdf_enc:
            yield item_html
            return
        existing_pay = list(item_html.get("payment_options") or [])
        existing_enc = list(item_html.get("encumbrances") or [])
        merged_pay = _dedup_clauses(existing_pay + pdf_pay, key="kind")
        merged_enc = _dedup_clauses(existing_enc + pdf_enc, key="kind")
        if len(merged_pay) == len(existing_pay) and len(merged_enc) == len(existing_enc):
            # PDF não trouxe nada novo — yielda item HTML como está
            self.log_event(
                "soleon_edital_no_diff",
                lot_url=item_html.get("url"),
                edital_url=response.url,
                merged_pay=len(merged_pay),
                merged_enc=len(merged_enc),
            )
            yield item_html
            return
        new_item = item_html.copy()
        new_item["payment_options"] = merged_pay
        new_item["encumbrances"] = merged_enc
        self.log_event(
            "soleon_edital_yield",
            lot_url=new_item.get("url"),
            edital_url=response.url,
            pay=[p["kind"] for p in merged_pay],
            enc=[(e["kind"], e.get("status")) for e in merged_enc],
        )
        yield new_item


# ---------------------------------------------------------------------------
# Helpers locais (puro Python, fáceis de testar isoladamente)
# ---------------------------------------------------------------------------


_IMOVEL_LABEL_RE = re.compile(r"\b(?:matr[ií]cula|endere[çc]o|cri|inscri[çc][ãa]o imobili[áa]ria)\s*:", re.I)
_IMOVEL_NOUN_RE = re.compile(
    r"\b(apartamento|casa|terreno|im[óo]vel|im[óo]veis|sala\s+comercial|loja|fazenda|"
    r"ch[áa]cara|s[íi]tio|gleba|kitnet|cobertura|sobrado|conjunto\s+comercial|"
    r"galp[ãa]o|pr[ée]dio)\b",
    re.I,
)
_VEICULO_LABEL_RE = re.compile(r"\b(?:placa|chassi|renavam|combust[íi]vel)\s*:", re.I)
_VEICULO_NOUN_RE = re.compile(
    r"\b(ve[íi]culo|motocicleta|caminh[ãa]o|caminhonete|trator|embarca[çc][ãa]o|"
    r"motoneta|reboque|[ôo]nibus|moto\s+\w+\s+ano)\b",
    re.I,
)


def _card_category(card) -> bool | None:
    """Classifica card de listagem SOLEON como imóvel.

    Retorna:
        True  — sinais fortes de imóvel (segue, não precisa rever no detail)
        False — sinais fortes de não-imóvel (descarta sem fetch)
        None  — ambíguo (segue, mas re-valida no detail via og:description)
    """
    text = " ".join(card.css("*::text").getall())
    has_imovel_label = bool(_IMOVEL_LABEL_RE.search(text))
    has_veiculo_label = bool(_VEICULO_LABEL_RE.search(text))
    has_imovel_noun = bool(_IMOVEL_NOUN_RE.search(text))
    has_veiculo_noun = bool(_VEICULO_NOUN_RE.search(text))

    # Sinais de imóvel mandam quando coexistem (lote misto que cita "imóvel")
    if has_imovel_label or has_imovel_noun:
        return True
    if has_veiculo_label or has_veiculo_noun:
        return False
    return None


def _normalize_text(s: str) -> str:
    """Espaços únicos, sem leading/trailing. Mantém acentuação."""
    return re.sub(r"\s+", " ", s or "").strip()


def _find_edital_url(item) -> str | None:
    """Localiza URL do edital principal (não complementar) em item['documents']."""
    for doc in (item.get("documents") or []):
        if not isinstance(doc, dict):
            continue
        label = (doc.get("name") or "").lower()
        url = doc.get("url") or ""
        if not url:
            continue
        # Edital principal: nome contém "edital" sem "complement", ou URL termina .pdf
        # com palavra "edital" no path.
        if "edital" in label and "complement" not in label:
            return url
        if "edital" in url.lower() and url.lower().endswith(".pdf"):
            return url
    return None


def _pdf_to_text(pdf_bytes: bytes) -> str:
    """Extrai texto de PDF in-memory via pypdf. Retorna '' se falhar."""
    if not pdf_bytes:
        return ""
    import io
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""


# ------- Parser de cláusulas (payment_option + encumbrance) -------------------
# Sinais detectados em texto livre da página `/leilao/{id}/lotes` (e do
# detail). Granularidade: presença de cada `kind`. Status default = "declarado".
# Refinamento de status (sub_rogado vs quitado_pelo_arrematante) e valores
# (amount, max_installments) é trabalho futuro — exige parser estrutural do
# edital ou regex muito específicas por leiloeiro.

_PAYMENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bfgts\b", re.I), "fgts"),
    (re.compile(r"\bfinanciamento(?:\s+banc[áa]rio|\s+pr[óo]prio)?\b", re.I), "financiamento_proprio"),
    (re.compile(r"\bcons[óo]rcio\b", re.I), "consorcio"),
    (re.compile(r"carta\s+de\s+cr[ée]dito", re.I), "carta_credito"),
    (re.compile(r"\bpermuta\b", re.I), "permuta"),
    (re.compile(r"\b(?:[àa]\s+vista)\b", re.I), "a_vista"),
]

# kind 'parcelado' tratado em separado pra extrair max_installments e entrada.
_PARC_PRESENT_RE = re.compile(r"\bparcelad[oa]s?\b|parcelament[oa]", re.I)
_PARC_INSTALLMENTS_RE = re.compile(
    r"(?:em\s+at[ée]\s+|at[ée]\s+|em\s+)(\d{1,3})\s*(?:parcelas?|x\b|vezes\b)",
    re.I,
)
_DOWN_PAYMENT_RE = re.compile(
    r"(\d{1,2})\s*%\s+(?:do\s+(?:lance|valor)|de\s+entrada|à\s+vista|a\s+vista)",
    re.I,
)

_ENCUMBRANCE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # IPTU em aberto: presença direta — o termo só aparece em editais quando
    # o débito é relevante. Ruído quase nulo.
    (re.compile(r"\biptu\b", re.I), "iptu_em_aberto"),
    # Condomínio em aberto: exige contexto financeiro pra evitar casar nome
    # de edifício ("CONDOMÍNIO EDIFÍCIO X").
    (re.compile(
        r"(?:d[ée]bit|d[íi]vid|cota|taxa|tribut|cr[ée]dit|m[êe]s|valor|atraso)\w*\s+(?:de\s+)?condomin",
        re.I,
    ), "condominio_em_aberto"),
    (re.compile(r"condomin\w*\s+em\s+(?:aberto|atraso)", re.I), "condominio_em_aberto"),
    (re.compile(r"d[ée]bito\s+condominial", re.I), "condominio_em_aberto"),
    (re.compile(r"\bhipoteca\b", re.I), "hipoteca"),
    (re.compile(r"\bpenhora\s+fiscal\b", re.I), "penhora_fiscal"),
    (re.compile(r"\bpenhora\b", re.I), "penhora"),
    (re.compile(r"aliena[çc][ãa]o\s+fiduci[áa]ri", re.I), "alienacao_fiduciaria"),
    (re.compile(r"indisponibilidade", re.I), "indisponibilidade"),
    (re.compile(r"\busufruto\b", re.I), "usufruto"),
    (re.compile(r"\barresto\b", re.I), "arresto"),
]

# Boilerplate CTN art. 130 (parágrafo único): tributos sobre o imóvel e
# taxas de condomínio sub-rogam-se na pessoa do arrematante. Aparece em
# praticamente todo leilão judicial. Quando detectado, adiciona iptu +
# condominio com status 'sub_rogado_no_lance' (mesmo se palavras-chave
# diretas não tiverem casado — caso ceruli/3torres template federal).
_CTN_130_RE = re.compile(
    r"(?:"
    r"art(?:\.|igo)?\s*130\s+do\s+(?:c\.?\s*t\.?\s*n|c[óo]digo\s+tribut[áa]rio)|"
    r"sub[-\s]?rog\w*\s+(?:na\s+)?pessoa\s+do\s+(?:adquirente|arrematante)|"
    r"cr[ée]ditos\s+tribut[áa]rios.{0,80}sub[-\s]?rog|"
    r"impost\w+\s+cujo\s+fato\s+gerador\s+seja\s+a\s+propriedade"
    r")",
    re.I,
)

# Sinais de status. Aplicados a TODAS as encumbrances detectadas no texto
# (heurística rasa — refinamento por encumbrance individual exige parser
# estrutural de cláusulas).
_STATUS_SUB_ROGADO_RE = re.compile(
    r"sub[-\s]?rog\w*|"
    r"art(?:\.|igo)?\s*130\s+do\s+(?:c\.?\s*t\.?\s*n|c[óo]digo\s+tribut[áa]rio)",
    re.I,
)
_STATUS_QUITADO_ARREMATANTE_RE = re.compile(
    r"(?:"
    r"(?:respons[áa]vel|arcar[áa]?\s*com|caber[áa]?\s+ao|"
    r"a\s+cargo\s+do|obriga[çc][ãa]o\s+do|"
    r"correr[áa]o\s+por\s+conta\s+do).{0,30}arrematante|"
    r"arrematante.{0,40}(?:arcar[áa]?|responder|quitar|assumir|pagar)"
    r")",
    re.I,
)


def _parse_auction_clauses(text: str) -> tuple[list[dict], list[dict]]:
    """Extrai (payment_options, encumbrances) de texto livre de uma página de leilão.

    Retorna listas de dicts com `kind` (sempre) e atributos opcionais:
      - payment: max_installments, min_down_payment_pct, notes
      - encumbrance: status (default 'declarado'), description
    """
    if not text:
        return [], []

    payments: list[dict] = []
    seen_kinds: set[str] = set()

    for pat, kind in _PAYMENT_PATTERNS:
        if kind not in seen_kinds and pat.search(text):
            payments.append({"kind": kind})
            seen_kinds.add(kind)

    if _PARC_PRESENT_RE.search(text) and "parcelado" not in seen_kinds:
        parc: dict = {"kind": "parcelado"}
        m_n = _PARC_INSTALLMENTS_RE.search(text)
        if m_n:
            parc["max_installments"] = int(m_n.group(1))
        m_dp = _DOWN_PAYMENT_RE.search(text)
        if m_dp:
            parc["min_down_payment_pct"] = m_dp.group(1)
        payments.append(parc)
        seen_kinds.add("parcelado")

    encumbrances: list[dict] = []
    enc_seen: set[str] = set()
    for pat, kind in _ENCUMBRANCE_PATTERNS:
        if kind in enc_seen:
            continue
        if pat.search(text):
            encumbrances.append({"kind": kind, "status": "declarado"})
            enc_seen.add(kind)

    # CTN art. 130: adiciona IPTU + condomínio (taxas) com status sub-rogado.
    # Cobre edital judicial federal típico que não nomeia "IPTU" diretamente.
    if _CTN_130_RE.search(text):
        for k in ("iptu_em_aberto", "condominio_em_aberto"):
            if k not in enc_seen:
                encumbrances.append({"kind": k, "status": "sub_rogado_no_lance"})
                enc_seen.add(k)

    # Refina status das encumbrances 'declarado' baseado em sinais textuais:
    #  - sub-rogação explícita → 'sub_rogado_no_lance'
    #  - "responsabilidade do arrematante" → 'quitado_pelo_arrematante'
    has_subrog = bool(_STATUS_SUB_ROGADO_RE.search(text))
    has_quitar = bool(_STATUS_QUITADO_ARREMATANTE_RE.search(text))
    if has_subrog or has_quitar:
        new_status = "sub_rogado_no_lance" if has_subrog else "quitado_pelo_arrematante"
        for e in encumbrances:
            if e["status"] == "declarado":
                e["status"] = new_status

    return payments, encumbrances


def _dedup_clauses(items: list[dict], key: str) -> list[dict]:
    """Deduplica por `key`. Em colisão, prefere entrada com status mais
    informativo que 'declarado' (ex.: 'sub_rogado_no_lance' ganha de
    'declarado' quando ambos kind=iptu_em_aberto coexistem)."""
    out: list[dict] = []
    idx: dict[Any, int] = {}
    for it in items:
        k = it.get(key)
        if k is None:
            continue
        if k not in idx:
            idx[k] = len(out)
            out.append(it)
            continue
        existing = out[idx[k]]
        existing_status = existing.get("status") or "declarado"
        new_status = it.get("status") or "declarado"
        if existing_status == "declarado" and new_status != "declarado":
            out[idx[k]] = it
    return out


# Sinais positivos de imóvel no og:title/og:description.
# Lista derivada de uma amostra representativa de leilões judiciais e
# extrajudiciais SOLEON (categorias que efetivamente aparecem nos editais).
_DETAIL_IMOVEL_RE = re.compile(
    r"\b("
    r"im[óo]vel|im[óo]veis|"
    r"apartamento|apto\.?\s+\d|kitnet|conjugado|cobertura|sobrado|"
    r"casa\b|residencial\b|"
    r"terreno|lote(s)?\s+(de\s+terreno|de\s+esquina|residencia)|"
    r"fazenda|ch[áa]cara|s[íi]tio|gleba|hectare\b|"
    r"sala\s+comercial|loja\b|galp[ãa]o|pr[ée]dio|edif[íi]cio\b|"
    r"[áa]rea\s+(rural|urbana|de\s+terra|construida)|"
    r"fra[çc][ãa]o\s+(de|do|da)\s+(im[óo]vel|terreno|fazenda|casa|apartamento)|"
    r"matr[íi]cula\s+n[º°o.]*\s*\d|matr[íi]cula\s+\d|"
    r"unidade\s+aut[ôo]noma|vaga\s+de\s+garagem|"
    r"loteamento\b|condom[íi]nio\s+residencial"
    r")\b",
    re.I,
)

# Sinais negativos: bens móveis tipicamente leiloados que NÃO são imóveis.
# Cobre veículos, equipamentos industriais/agrícolas, eletrodomésticos,
# semoventes, commodities/matérias-primas.
_DETAIL_NON_IMOVEL_RE = re.compile(
    r"\b("
    r"ve[íi]culo|caminh[ãa]o|caminhonete|camionete|motocicleta|motoneta|"
    r"\bmoto\s+\w+|trator|[ôo]nibus|micro-?[ôo]nibus|reboque|carreta\b|"
    r"automotor|empilhadeira|retroescavadeira|escavadeira|"
    r"colheitadeira|plantadeira|"
    r"m[áa]quina|equipamento|implemento\s+agr|gerador|"
    r"computador|notebook|impressora|servidor\s+rack|"
    r"eletrodom[ée]stico|geladeira|fog[ãa]o|televis[ãa]o|"
    r"m[óo]vel\s+de\s+(escrit|copa|cozinha|sala)|m[óo]veis\s+e\s+|"
    r"esteira\s+ergom|passadeira|"
    r"bovino|equino|su[íi]no|gado\b|semovent|cabe[çc]as?\s+de\s+gado|"
    r"tonelada|sucata|peça(s)?\s+de\s+\w+|saca(s)?\s+de\s+\w+|"
    r"bens\s+diversos|bens\s+m[óo]veis|"
    r"\d+\s*\(\w+\)\s+(camas?|cadeiras?|mesas?|estantes?)"
    r")\b",
    re.I,
)

_DETAIL_DATE_PREFIX_RE = re.compile(
    r"\bleil[ãa]o\s*:\s*\d{1,2}/\d{1,2}/\d{4}[^,]*,\s*",
    re.I,
)


def _detail_is_imovel(og_title: str | None, og_desc: str | None) -> bool:
    """Decide pelo og:title+og:description se o lote é imóvel.

    Estrito: na ausência de sinais positivos, retorna False (drop).
    Esse default conservador surgiu de smoke em isaiasleiloes, onde 37%
    dos lots eram bens móveis (veículo, colheitadeira, máquinas, móveis,
    commodities) e o filtro de prefixo anterior não os pegava — o template
    do isaias prefixa toda og:description com 'Leilão: DD/MM/YYYY às HH:MM,'.
    """
    title = (og_title or "")
    desc = (og_desc or "")
    # Remove prefixo de data que existe nos templates judiciais
    desc = _DETAIL_DATE_PREFIX_RE.sub(" ", desc)
    text = (title + " " + desc).lower()
    has_pos = bool(_DETAIL_IMOVEL_RE.search(text))
    has_neg = bool(_DETAIL_NON_IMOVEL_RE.search(text))
    if has_pos:
        # Coexistência (ex.: "imóvel + 1 veículo no mesmo lote") aceita.
        return True
    if has_neg:
        return False
    # Sem sinal positivo — drop por segurança.
    return False


_STATUS_MAP = {
    # Classes da div.label_lote no template SOLEON. Múltiplos templates
    # geram múltiplas classes; este mapa cobre tudo que aparece em amostra
    # de 1000+ lots dos 53 tenants amostrados.
    "aberto_lance":   "aberto",       # leilão online, recebendo lances
    "venda_direta":   "aberto",       # modalidade "venda direta" = aberto pra propostas
    "proposta":       "aberto",       # aberto pra recebimento de propostas
    "sem_licitante":  "cancelado",    # encerrado sem arrematante (deserto)
    "vendido":        "arrematado",
    "arrematado":     "arrematado",
    "sustado":        "cancelado",
    "suspenso":       "suspenso",
    "encerrado":      "desconhecido", # encerrado sem mais info — pipeline preserva
}


def _map_status(class_attr: str) -> str:
    classes = (class_attr or "").lower()
    for key, value in _STATUS_MAP.items():
        if key in classes:
            return value
    return "desconhecido"


_BRL_RE = re.compile(r"R\$\s*([\d.,]+)")
_IMG_BENS_RE = re.compile(
    r"https?://[^\s'\"\\]+?/(?:watermark/)?bens/[^\s'\"\\]+?\.(?:jpg|jpeg|png|webp)",
    re.I,
)


def _extract_brl_from_og_title(og_title: str, label: str) -> str | None:
    """Extrai R$ que segue um rótulo no og:title.

    SOLEON padroniza og:title como '<localização> - Lance Inicial: R$X- Avaliação: R$Y'.
    Útil para tenants que não têm <h6> com o label (template venda direta).
    """
    if not og_title:
        return None
    m = re.search(rf"{re.escape(label)}\s*:\s*R\$\s*([\d.,]+)", og_title, re.I)
    if not m:
        return None
    try:
        return str(_brl_to_decimal(m.group(1)))
    except (InvalidOperation, ValueError):
        return None


def _extract_brl_after_label(response, labels: list[str]) -> str | None:
    """Procura R$ NNN no texto que segue um <h6> contendo cada label."""
    for label in labels:
        text = " ".join(
            response.xpath(
                f"//h6[contains(., {label!r})]/following-sibling::*[1]//text() | "
                f"//h6[contains(., {label!r})]//text()"
            ).getall()
        )
        m = _BRL_RE.search(text)
        if m:
            try:
                return str(_brl_to_decimal(m.group(1)))
            except (InvalidOperation, ValueError):
                continue
    return None


def _text_after_label(response, labels: list[str]) -> str:
    for label in labels:
        text = " ".join(
            response.xpath(
                f"//h6[contains(., {label!r})]//text()"
            ).getall()
        ).strip()
        if text:
            return text
    return ""


def _brl_to_decimal(raw: str) -> Decimal:
    """'1.234,56' → Decimal('1234.56'). '1234' → Decimal('1234')."""
    s = raw.strip().replace(".", "").replace(",", ".")
    return Decimal(s)


_BR_DT_RE = re.compile(
    # Aceita "DD/MM/YYYY HH:MM:SS", "DD/MM/YYYY às HH:MM", "DD/MM/YYYY - HH:MM"
    r"(\d{2})/(\d{2})/(\d{4})\s*(?:[àa]s|-)?\s*(\d{2}):(\d{2})(?::(\d{2}))?"
)


def _parse_br_datetime_iso(text: str) -> str | None:
    m = _BR_DT_RE.search(text)
    if not m:
        return None
    d, mth, y, h, mi, s = m.groups()
    return f"{y}-{mth}-{d}T{h}:{mi}:{s or '00'}-03:00"


def _parse_address(raw: str) -> dict:
    """Heurística simples sobre 'Rua X, 14 - Bairro - Cidade / UF'."""
    cleaned = re.sub(r"\s+", " ", raw).strip()
    out: dict[str, Any] = {"raw_text": cleaned}
    # UF no fim: "/ XX"
    m = re.search(r"/\s*([A-Z]{2})\s*$", cleaned)
    if m:
        out["state"] = m.group(1)
    # Cidade entre " - " e "/UF"
    m = re.search(r"-\s*([^-/]+?)\s*/\s*[A-Z]{2}\s*$", cleaned)
    if m:
        out["city"] = m.group(1).strip()
    # Bairro: penúltimo segmento separado por " - "
    parts = [p.strip() for p in cleaned.split(" - ")]
    if len(parts) >= 3:
        out["neighborhood"] = parts[-2]
    # Rua + número: primeiro segmento
    if parts:
        m = re.match(r"^(.+?),\s*([\dSNs/-]+)\s*$", parts[0])
        if m:
            out["street"] = m.group(1).strip()
            out["number"] = m.group(2).strip()
        else:
            out["street"] = parts[0]
    return out


def _extract_bids(response) -> list[dict]:
    """Histórico de lances SOLEON em div.ult_body div.ultimos-lances-item."""
    bids: list[dict] = []
    for item in response.css("div.ult_body div.ultimos-lances-item"):
        valor_raw = item.css(".ult_valor_lance::text").get() or ""
        data_raw = item.css(".ult_data_lance::text").get() or ""
        usuario = (item.css(".ult_usuario_lance::text").get() or "").strip()
        m_valor = _BRL_RE.search(valor_raw)
        if not m_valor:
            continue
        try:
            value = _brl_to_decimal(m_valor.group(1))
        except (InvalidOperation, ValueError):
            continue
        ts = _parse_br_datetime_iso(data_raw)
        if not ts:
            continue
        bids.append({
            "timestamp": ts,
            "value_brl": str(value),
            "bidder_raw": usuario or None,
        })
    return bids
