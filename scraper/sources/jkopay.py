"""街口（mkt.jkopay.com）：活動總覽頁 newevent → campaign 明細頁。

Next.js App Router 站：campaign 內文不在 DOM，而在 RSC flight payload
（``self.__next_f.push([1,"…"])`` 的字串 chunk）；解碼後抽中文文字段。
標題與活動摘要在 og:title / og:description（伺服器渲染，穩定可取）。
"""

import json
import logging
import re
from collections.abc import Callable
from datetime import datetime

from bs4 import BeautifulSoup, SoupStrainer

from scraper.dates import parse_period, parse_period_near
from scraper.models import Offer
from scraper.sources._shared import fetch_listed_details

logger = logging.getLogger(__name__)

PROVIDER = "街口"
_BASE = "https://mkt.jkopay.com"
LISTING_URL = f"{_BASE}/zh-TW/campaign/newevent"
_LISTING_SLUG = "newevent"

# 站內 campaign 連結出現在 href 屬性或 RSC payload 的跳脫字串裡，
# 兩者路徑前一個字元都是引號；要求引號或本站 host 開頭，擋掉他站資產路徑（CDN 圖檔等）
_CAMPAIGN_PATH = re.compile(r'(?:"|mkt\.jkopay\.com)(?:/zh-TW)?/campaign/([A-Za-z0-9_-]+)')
_PUSH_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
_MIN_RUN_LENGTH = 6
# 內文文字段：以中文起頭、只收人話常見字元（不含引號/反斜線/角括號，天然擋 payload 原始碼）
_TEXT_RUN = re.compile(
    r"[一-鿿][一-鿿0-9A-Za-z％%~～〜—／/－\-．.。、，,！!？?：:；;（）()「」【】\s]"
    rf"{{{_MIN_RUN_LENGTH - 1},}}"
)
# 效期標記的優先序：正式活動期間 > 領券/折抵窗口
_PERIOD_MARKERS = ("活動期間", "活動時間", "優惠期間", "領券時間", "折抵時間")


def list_campaign_urls(listing_html: str) -> list[str]:
    """活動總覽頁 → campaign 絕對網址（去重、保序、不含總覽頁自己）。"""
    return list(
        dict.fromkeys(
            f"{_BASE}/zh-TW/campaign/{slug}"
            for slug in _CAMPAIGN_PATH.findall(listing_html)
            if slug != _LISTING_SLUG
        )
    )


def parse_campaign(campaign_html: str, url: str, scraped_at: datetime) -> Offer:
    """campaign 頁 → Offer；抽不到標題或內文視為版面已改，raise ValueError。"""
    # 只解析 meta 標籤：campaign 頁動輒 200KB，全頁建 DOM 只為了讀兩個 og 標籤太浪費
    soup = BeautifulSoup(campaign_html, "html.parser", parse_only=SoupStrainer("meta"))
    title = _og_content(soup, "og:title")
    if not title:
        raise ValueError(f"街口 campaign 頁缺 og:title，版面可能已改：{url}")

    description = _og_content(soup, "og:description")
    lines = [description] if description else []
    content = "\n".join(dict.fromkeys(lines + _payload_text_runs(campaign_html)))
    if not content:
        raise ValueError(f"街口 campaign 頁抽不到內文，版面可能已改：{url}")

    # 效期只信標題或活動時間類標記附近的日期；不做全文掃描——
    # 街口幣到期說明等樣板文字帶過去年份的日期，掃到會讓常青活動被誤判過期
    valid_from, valid_to = parse_period(title)
    if valid_from is None:
        valid_from, valid_to = parse_period_near(
            content, markers=_PERIOD_MARKERS, full_scan=False
        )
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
    """總覽頁 → campaign 去重後逐頁抓；單頁失敗記 WARNING 跳過。"""
    return fetch_listed_details(get, [LISTING_URL], list_campaign_urls, parse_campaign, logger)


def _og_content(soup: BeautifulSoup, property_name: str) -> str:
    tag = soup.find("meta", property=property_name)
    if tag is None:
        return ""
    return (tag.get("content") or "").strip()


def _payload_text_runs(campaign_html: str) -> list[str]:
    """RSC flight payload → 人話文字段（JSON 解碼、正規化空白、去重保序）。"""
    runs: list[str] = []
    for chunk in _PUSH_CHUNK.findall(campaign_html):
        try:
            decoded = json.loads(f'"{chunk}"')
        except json.JSONDecodeError:
            continue  # 非 JSON 相容跳脫的 chunk 不含可讀內文，跳過
        for run in _TEXT_RUN.findall(decoded):
            normalized = re.sub(r"\s+", " ", run).strip()
            if len(normalized) >= _MIN_RUN_LENGTH:
                runs.append(normalized)
    return list(dict.fromkeys(runs))
