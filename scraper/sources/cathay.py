"""國泰世華（cathay-cube.com.tw）：sitemap 列活動頁 + AEM ``.model.json`` 內容 API。

活動頁 URL 形如 ``.../event/overview/credit-card/<分類>/<年月>/<活動代碼>``（三層）；
一、二層是分類與年月列表頁，不是單一活動。每頁掛 ``.model.json`` 拿結構化內容，
文字藏在 ``cub_texta``（活動期間）、``cub_textb`` / ``cub_notice``（內文）元件裡。
"""

import json
import logging
import re
from collections.abc import Callable
from datetime import datetime

from bs4 import BeautifulSoup

from scraper.dates import parse_period
from scraper.models import Offer
from scraper.sources._shared import SKIPPABLE_ERRORS

logger = logging.getLogger(__name__)

BANK = "國泰世華"
SITEMAP_URL = "https://www.cathay-cube.com.tw/sitemap.xml"
_EVENT_MARKER = "/event/overview/credit-card/"
_LOC = re.compile(r"<loc>([^<]+)</loc>")
_TEXT_COMPONENT_PREFIXES = ("cub_text", "cub_notice")


def list_event_urls(sitemap_xml: str) -> list[str]:
    """從 sitemap 取出單一活動頁（credit-card 下三層路徑），排除分類/年月列表頁。"""
    urls = []
    for loc in _LOC.findall(sitemap_xml):
        url = loc.strip()
        if _EVENT_MARKER not in url:
            continue
        tail = url.split(_EVENT_MARKER, 1)[1].strip("/")
        if len(tail.split("/")) == 3:
            urls.append(url)
    return urls


def parse_event(model_json_text: str, url: str, scraped_at: datetime) -> Offer:
    """把一個活動頁的 .model.json 轉成 Offer；缺 title 或內文視為版面已改，raise ValueError。"""
    data = json.loads(model_json_text)
    raw_title = data.get("title") or ""
    title = raw_title.split("｜")[0].strip()
    if not title:
        raise ValueError(f"國泰活動頁缺 title，版面可能已改：{url}")

    texts = _collect_component_texts(data)
    content = "\n".join(t for t in (_strip_html(t) for t in texts) if t)
    if not content:
        raise ValueError(f"國泰活動頁抽不到內文，版面可能已改：{url}")

    valid_from, valid_to = (None, None)
    for text in texts:
        valid_from, valid_to = parse_period(text)
        if valid_from:
            break

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
    """sitemap → 逐活動頁抓 .model.json；單頁失敗（解析不出、暫時性 HTTP 錯誤、
    非 JSON 回應）記 WARNING 跳過，不拖垮整個來源。"""
    offers = []
    for url in list_event_urls(get(SITEMAP_URL)):
        try:
            offers.append(parse_event(get(url + ".model.json"), url, datetime.now()))
        except SKIPPABLE_ERRORS as error:  # JSONDecodeError 是 ValueError 子類，一併涵蓋
            logger.warning("跳過國泰活動頁 %s：%s", url, error)
    return offers


def _collect_component_texts(node: object) -> list[str]:
    """深度優先走 AEM 元件樹，收集 cub_text* / cub_notice* 元件的 text。

    ``:items`` 的子元件依同層 ``:itemsOrder`` 排序（顯示順序），沒列到的補在後面；
    JSON 鍵序不保證等於顯示順序，直接遵 dict 序內文段落可能錯亂。
    """
    texts: list[str] = []
    if isinstance(node, dict):
        items = node.get(":items")
        if isinstance(items, dict):
            for key in _display_order(node, items):
                value = items[key]
                if (
                    key.startswith(_TEXT_COMPONENT_PREFIXES)
                    and isinstance(value, dict)
                    and isinstance(value.get("text"), str)
                ):
                    texts.append(value["text"])
                texts.extend(_collect_component_texts(value))
        for key, value in node.items():
            if key != ":items":
                texts.extend(_collect_component_texts(value))
    elif isinstance(node, list):
        for item in node:
            texts.extend(_collect_component_texts(item))
    return texts


def _display_order(node: dict, items: dict) -> list[str]:
    order = node.get(":itemsOrder")
    keys = [k for k in order if k in items] if isinstance(order, list) else []
    return keys + [k for k in items if k not in keys]


def _strip_html(text: str) -> str:
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)
