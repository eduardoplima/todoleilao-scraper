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
        # Rede de segurança: re-checa categoria via og:description no detalhe.
        # Pega lotes que passaram ambíguos pelo card e revela ser veículo.
        og_desc = (response.css("meta[property='og:description']::attr(content)").get() or "").lower()
        if _detail_is_non_imovel(og_desc):
            self.log_event(
                "soleon_lote_dropped_non_imovel",
                url=response.url,
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

        # description — div com "Descrição:" como heading
        desc = " ".join(response.css("div:contains('Descrição:') *::text").getall()).strip()
        if desc:
            # Limpa o "Descrição:" prefix repetido
            desc = re.sub(r"^\s*Descri[çc][aã]o:\s*", "", desc, count=1)
            loader.add_value("description", desc[:5000])

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
        yield item


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
    # IPTU em aberto: cuidado pra não casar nome de bairro etc. — sempre
    # exigir contexto de débito/aberto/atraso/dívida ou simplesmente a
    # palavra IPTU (que praticamente só aparece quando está em aberto).
    (re.compile(r"\biptu\b", re.I), "iptu_em_aberto"),
    (re.compile(
        r"(?:d[ée]bit|d[íi]vid|cota|taxa|condom[íi]nio\s+em\s+(?:aberto|atraso))[^.]{0,40}condomin",
        re.I,
    ), "condominio_em_aberto"),
    (re.compile(r"condom[íi]ni(?:o|al)s?\s+em\s+(?:aberto|atraso)", re.I), "condominio_em_aberto"),
    (re.compile(r"\bhipoteca\b", re.I), "hipoteca"),
    (re.compile(r"\bpenhora\s+fiscal\b", re.I), "penhora_fiscal"),
    (re.compile(r"\bpenhora\b", re.I), "penhora"),
    (re.compile(r"aliena[çc][ãa]o\s+fiduci[áa]ri", re.I), "alienacao_fiduciaria"),
    (re.compile(r"indisponibilidade", re.I), "indisponibilidade"),
    (re.compile(r"\busufruto\b", re.I), "usufruto"),
    (re.compile(r"\barresto\b", re.I), "arresto"),
]


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

    return payments, encumbrances


def _dedup_clauses(items: list[dict], key: str) -> list[dict]:
    """Remove dicts com mesmo valor em `key`, mantendo o primeiro (que tende
    a ser o do leilão genérico, sobreposto por specs do detail só se novos)."""
    out: list[dict] = []
    seen: set[Any] = set()
    for it in items:
        k = it.get(key)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


_DETAIL_NON_IMOVEL_PREFIXES = (
    "um veículo",
    "um veiculo",
    "uma motocicleta",
    "um caminhão",
    "um caminhao",
    "uma caminhonete",
    "um trator",
    "uma embarcação",
    "uma embarcacao",
    "uma motoneta",
    "um reboque",
    "um ônibus",
    "um onibus",
    "uma moto ",
)


def _detail_is_non_imovel(og_desc_lower: str) -> bool:
    """Rede de segurança no detail. True = lote NÃO é imóvel, deve ser dropado."""
    if not og_desc_lower:
        return False
    return og_desc_lower.lstrip().startswith(_DETAIL_NON_IMOVEL_PREFIXES)


_STATUS_MAP = {
    "aberto_lance": "aberto",
    "sem_licitante": "cancelado",  # encerrado sem arrematante
    "vendido": "arrematado",
    "sustado": "cancelado",
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
