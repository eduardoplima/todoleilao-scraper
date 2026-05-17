"""Constantes de User-Agent compartilhadas entre scripts de discovery.

Espelha `scrapy_project/leilao_scraper/spiders/_common_ua.py` (sem import
cross-package). Atualizar ambos juntos.
"""
from __future__ import annotations

# Chrome 122 (Feb 2025) — simula browser real. Bypassa WAF de sites como
# fidelisleiloes.com.br que retornavam placeholder pra UA bot.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# Bot identificável — usar SÓ em APIs públicas que aceitam (INNLEI, Nominatim).
BOT_USER_AGENT = "TodoLeilaoBot/0.1 (+contato: eplima.cc@gmail.com)"
