"""台北富邦（cardpromote.taipeifubon.com.tw）：優惠專站分類頁 + 明細頁，全靜態渲染。

分類代碼 A–F，分類頁帶相對連結 ``Detail?sn=<編號>``；明細頁 title 帶
「富邦信用卡 - 」字首，主內容在 ``div.main-container``，
「你可能也喜歡」推薦區（``div.may-like``）要剔除以免混入別檔優惠。
"""

import logging
import re
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.dates import parse_period
from scraper.models import Offer
from scraper.sources._shared import fetch_listed_details

logger = logging.getLogger(__name__)

BANK = "台北富邦"
_BASE = "https://cardpromote.taipeifubon.com.tw/promotion/"
CATEGORY_URLS = [f"{_BASE}Type?category={code}" for code in "ABCDEF"]
_DETAIL_HREF = re.compile(r'href="((?:[^"]*/promotion/)?Detail\?sn=[A-Za-z0-9]+)"')
_TITLE_PREFIX = "富邦信用卡 - "
# 主內容以外全剔除：側欄促銷 swiper（swiper-container/discount-card）、推薦區、
# 選單、頁尾（footer-up/footer-dw + <footer>）。雜訊混入 content 會毒化 RAG 檢索
_EXCLUDED_SECTIONS = (
    "may-like",
    "menu-container",
    "footer-up",
    "footer-dw",
    "swiper-container",
    "discount-card",
)


def list_detail_urls(category_html: str) -> list[str]:
    """分類頁 → 明細絕對網址（去重、保序）。"""
    seen: dict[str, None] = {}
    for href in _DETAIL_HREF.findall(category_html):
        seen.setdefault(urljoin(_BASE, href), None)
    return list(seen)


def parse_detail(detail_html: str, url: str, scraped_at: datetime) -> Offer:
    """明細頁 → Offer；抽不到標題或內文視為版面已改，raise ValueError。"""
    soup = BeautifulSoup(detail_html, "html.parser")
    if soup.title is None or not soup.title.get_text(strip=True):
        raise ValueError(f"富邦明細頁缺 title，版面可能已改：{url}")
    title = soup.title.get_text(strip=True).removeprefix(_TITLE_PREFIX).strip()

    for tag in soup.find_all(("footer", "nav", "header")):
        tag.decompose()
    for class_name in _EXCLUDED_SECTIONS:
        for section in soup.find_all("div", class_=class_name):
            section.decompose()
    container = soup.find("div", class_="main-container") or soup.body
    content = container.get_text(separator="\n", strip=True) if container else ""
    if not title or not content:
        raise ValueError(f"富邦明細頁抽不到標題或內文，版面可能已改：{url}")

    valid_from, valid_to = parse_period(content)
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
    """6 個分類頁 → 明細去重後逐頁抓；單頁失敗記 WARNING 跳過。"""
    return fetch_listed_details(get, CATEGORY_URLS, list_detail_urls, parse_detail, logger)
