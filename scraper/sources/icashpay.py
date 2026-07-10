"""icash Pay（icashpay.com.tw）：活動訊息列表（advertMessage，帶分頁）＋明細頁，全靜態渲染。

列表卡片連結分兩種：站內 ``/advertMessage/view/id/<id>``（要爬）與外連
icash.com.tw 的公告（版型不同，跳過）。明細在 ``div.detail-box``：
``h1`` 是標題、``article`` 是內文，活動期間寫在「活動期間」字樣附近。
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

PROVIDER = "icash Pay"
_BASE = "https://www.icashpay.com.tw"
INDEX_URL = f"{_BASE}/advertMessage/index"

_PAGE_PATH = re.compile(r"/advertMessage/index/page/(\d+)")
_DETAIL_HREF = re.compile(r'href="([^"]*?/advertMessage/view/id/\d+)"')


def list_page_urls(index_html: str) -> list[str]:
    """列表首頁 → 各分頁絕對網址（去重、保序）。"""
    return list(
        dict.fromkeys(
            f"{_BASE}/advertMessage/index/page/{n}" for n in _PAGE_PATH.findall(index_html)
        )
    )


def list_detail_urls(list_html: str) -> list[str]:
    """列表頁 → 站內明細絕對網址（去重、保序；外連公告卡片不收）。"""
    urls = (urljoin(_BASE, href) for href in _DETAIL_HREF.findall(list_html))
    return list(dict.fromkeys(u for u in urls if u.startswith(_BASE)))


def parse_detail(detail_html: str, url: str, scraped_at: datetime) -> Offer:
    """明細頁 → Offer；抽不到標題或內文視為版面已改，raise ValueError。"""
    soup = BeautifulSoup(detail_html, "html.parser")
    box = soup.find("div", class_="detail-box")
    if box is None:
        raise ValueError(f"icash Pay 明細頁缺 detail-box，版面可能已改：{url}")
    heading = box.find("h1")
    title = heading.get_text(strip=True) if heading else ""
    article = box.find("article")
    content = article.get_text(separator="\n", strip=True) if article else ""
    if not title or not content:
        raise ValueError(f"icash Pay 明細頁抽不到標題或內文，版面可能已改：{url}")

    valid_from, valid_to = parse_period_near(content)
    return Offer(
        source_type="e_payment",
        bank=None,
        provider=PROVIDER,
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
    """列表首頁抓分頁清單 → 各分頁明細去重後逐頁抓；單頁失敗記 WARNING 跳過。

    首頁本身就是第 1 頁：直接當第一個列表頁用（省一次重抓），分頁清單裡的
    page/1 剔除——就算日後改版把「目前頁」渲染成非連結，第 1 頁優惠也不會漏。
    """
    index_html = get(INDEX_URL)
    other_pages = [u for u in list_page_urls(index_html) if not u.endswith("/page/1")]
    cached_get = _with_cached_index(get, index_html)
    return fetch_listed_details(
        cached_get, [INDEX_URL, *other_pages], list_detail_urls, parse_detail, logger
    )


def _with_cached_index(get: Callable[[str], str], index_html: str) -> Callable[[str], str]:
    """INDEX_URL 回快取內容（剛抓過），其他 URL 照常打。"""

    def cached(url: str) -> str:
        return index_html if url == INDEX_URL else get(url)

    return cached
