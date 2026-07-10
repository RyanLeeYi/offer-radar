"""台新（mkpcard.taishinbank.com.tw）：優惠 CMS 分類列表頁 + 明細頁，全靜態渲染。

分類代碼 A–I（美饌料理、網購及 3C…），列表頁帶明細連結
``/tscccms/promotion/detail/WM_<時間戳>``，明細頁 title 帶「 ： 台新銀行」字尾，
內文在 ``div.page-content``，活動期間寫在「活動期間」字樣附近。
"""

import logging
import re
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.dates import parse_period_near
from scraper.models import Offer
from scraper.sources._shared import fetch_listed_details

logger = logging.getLogger(__name__)

BANK = "台新"
_BASE = "https://mkpcard.taishinbank.com.tw"
CATEGORY_URLS = [f"{_BASE}/tscccms/promotion/offerList/{code}" for code in "ABCDEFGHI"]
_DETAIL_HREF = re.compile(r'href="([^"]*?/tscccms/promotion/detail/[A-Za-z0-9_]+)"')
_TITLE_SUFFIX = " ： "  # <title>活動名 ： 台新銀行</title>，用完整分隔避免截到活動名裡的冒號


def list_detail_urls(list_html: str) -> list[str]:
    """列表頁 → 明細絕對網址（去重、保序）。"""
    seen: dict[str, None] = {}
    for href in _DETAIL_HREF.findall(list_html):
        seen.setdefault(urljoin(_BASE, href), None)
    return list(seen)


def parse_detail(detail_html: str, url: str, scraped_at: datetime) -> Offer:
    """明細頁 → Offer；抽不到標題或內文視為版面已改，raise ValueError。"""
    soup = BeautifulSoup(detail_html, "html.parser")
    if soup.title is None or not soup.title.get_text(strip=True):
        raise ValueError(f"台新明細頁缺 title，版面可能已改：{url}")
    title = soup.title.get_text().rsplit(_TITLE_SUFFIX, 1)[0].strip()

    container = soup.find("div", class_="page-content") or soup.body
    content = container.get_text(separator="\n", strip=True) if container else ""
    if not title or not content:
        raise ValueError(f"台新明細頁抽不到標題或內文，版面可能已改：{url}")

    valid_from, valid_to = parse_period_near(content)
    return Offer(
        source_type="credit_card",
        bank=BANK,
        provider=None,
        title=title,
        content=content,
        channel=None,
        reward_rate=None,
        valid_from=valid_from,
        valid_to=valid_to,
        source_url=url,
        scraped_at=scraped_at,
    )


def fetch(get: Callable[[str], str]) -> list[Offer]:
    """9 個分類列表 → 明細去重後逐頁抓；單頁失敗記 WARNING 跳過。"""
    return fetch_listed_details(get, CATEGORY_URLS, list_detail_urls, parse_detail, logger)
