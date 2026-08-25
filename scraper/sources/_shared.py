"""列表式來源（台新、富邦）共用的抓取管線：分類頁 → 明細去重 → 逐頁解析。

單頁失敗（解析不出或暫時性 HTTP 錯誤）記 WARNING 跳過，不拖垮整個來源；
列表頁本身失敗則往上拋，由 orchestrator 判定來源失敗。

F23 失敗頁存證（腿一）：解析擲例外、或列表頁抓取成功但解析出 0 筆明細連結（版面可能
已改），把該頁原始 HTML 存進失敗頁存證區並記 WARNING，不中斷該輪其他頁／來源。
只有「解析」失敗才存證——HTTP 抓取本身失敗（暫時性錯誤）沒有 HTML 可存，且下次重跑
自然會重試，不需要自癒。存證區同時是修復迴圈的 fixture 來源，見
docs/self-heal-fixture-loop.md。
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote

import requests

from scraper.models import Offer

ParseDetail = Callable[[str, str, datetime], Offer]
SKIPPABLE_ERRORS = (ValueError, requests.RequestException)

# data/ 已在 .gitignore（同 offers.db、chroma），失敗頁存證比照放這裡
FAILED_PAGES_DIR = Path("data/failed_pages")

_ARCHIVE_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class FailedPage:
    """一筆失敗頁存證：scraper 側寫入、rag/selfheal.py 讀出消化，也可直接當測試 fixture。"""

    source: str
    url: str
    reason: str  # "parse_error"（解析擲例外）｜"zero_results"（解析出 0 筆連結）
    archived_at: datetime
    html: str
    # 讀出存證區時是實際路徑；rag/selfheal.py 測試用的合成 FailedPage 不需要，留 None
    path: Path | None = None


def archive_failed_page(
    source: str,
    url: str,
    html: str,
    reason: str,
    when: datetime,
    dir_path: Path = FAILED_PAGES_DIR,
) -> Path | None:
    """把失敗頁原始 HTML 存進存證區（檔名含來源名與時間戳）。

    寫入失敗（如磁碟已滿）只記警告、不中斷爬蟲主流程——存證是買時間的 fallback，
    它自己不該變成新的失敗點。
    """
    filename = f"{source}__{when.strftime('%Y%m%dT%H%M%S')}__{reason}__{quote(url, safe='')}.html"
    path = dir_path / filename
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    except OSError as error:
        _ARCHIVE_LOGGER.warning("失敗頁存證寫入失敗，跳過：%s（%s）", url, error)
        return None
    return path


def read_failed_pages(dir_path: Path = FAILED_PAGES_DIR) -> list[FailedPage]:
    """讀出存證區所有失敗頁；檔名不符命名規則的檔案略過（防禦手動放入的雜項檔）。"""
    if not dir_path.is_dir():
        return []
    pages = []
    for path in sorted(dir_path.glob("*.html")):
        parsed = _parse_failed_page_filename(path.name)
        if parsed is None:
            continue
        source, archived_at, reason, url = parsed
        pages.append(
            FailedPage(
                source=source,
                url=url,
                reason=reason,
                archived_at=archived_at,
                html=path.read_text(encoding="utf-8"),
                path=path,
            )
        )
    return pages


def _parse_failed_page_filename(name: str) -> tuple[str, datetime, str, str] | None:
    parts = name.removesuffix(".html").split("__", 3)
    if len(parts) != 4:
        return None
    source, timestamp, reason, quoted_url = parts
    try:
        archived_at = datetime.strptime(timestamp, "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    return source, archived_at, reason, unquote(quoted_url)


def fetch_listed_details(
    get: Callable[[str], str],
    category_urls: list[str],
    list_detail_urls: Callable[[str], list[str]],
    parse_detail: ParseDetail,
    logger: logging.Logger,
    archive_dir: Path = FAILED_PAGES_DIR,
) -> list[Offer]:
    source_name = logger.name.rsplit(".", 1)[-1]
    detail_urls: dict[str, None] = {}
    for category_url in category_urls:
        category_html = get(category_url)  # 抓取本身失敗往上拋，既有行為不變
        urls = list_detail_urls(category_html)
        if not urls:
            logger.warning("列表頁 %s 解析出 0 筆連結，版面可能已改，存證備查", category_url)
            archive_failed_page(
                source_name, category_url, category_html, "zero_results", datetime.now(), archive_dir
            )
        for url in urls:
            detail_urls.setdefault(url, None)

    offers = []
    for url in detail_urls:
        try:
            detail_html = get(url)
        except SKIPPABLE_ERRORS as error:
            logger.warning("跳過明細頁 %s：%s", url, error)
            continue
        try:
            offers.append(parse_detail(detail_html, url, datetime.now()))
        except SKIPPABLE_ERRORS as error:
            logger.warning("跳過明細頁 %s：%s，存證備查", url, error)
            archive_failed_page(source_name, url, detail_html, "parse_error", datetime.now(), archive_dir)
    return offers
