"""列表式來源（台新、富邦）共用的抓取管線：分類頁 → 明細去重 → 逐頁解析。

單頁失敗（解析不出或暫時性 HTTP 錯誤）記 WARNING 跳過，不拖垮整個來源；
列表頁本身失敗則往上拋，由 orchestrator 判定來源失敗。
"""

import logging
from collections.abc import Callable
from datetime import datetime

import requests

from scraper.models import Offer

ParseDetail = Callable[[str, str, datetime], Offer]
SKIPPABLE_ERRORS = (ValueError, requests.RequestException)


def fetch_listed_details(
    get: Callable[[str], str],
    category_urls: list[str],
    list_detail_urls: Callable[[str], list[str]],
    parse_detail: ParseDetail,
    logger: logging.Logger,
) -> list[Offer]:
    detail_urls: dict[str, None] = {}
    for category_url in category_urls:
        for url in list_detail_urls(get(category_url)):
            detail_urls.setdefault(url, None)

    offers = []
    for url in detail_urls:
        try:
            offers.append(parse_detail(get(url), url, datetime.now()))
        except SKIPPABLE_ERRORS as error:
            logger.warning("跳過明細頁 %s：%s", url, error)
    return offers
