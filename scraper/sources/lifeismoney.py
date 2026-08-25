"""PTT Web 版 Lifeismoney（省錢）看板：純爬取（F21）。

只負責「列表頁 → 文章連結 → 文章原始文本」，不碰 LLM 抽取、不碰 DB——
兩者由 ``rag/ptt_extractor.py``、``rag/ptt_ingest.py`` 負責（scraper/ 不得 import rag/，
架構邊界見 CLAUDE.md／DECISIONS：LLM 抽取需重用 rag/llm.py，故放在 rag/ 側，比照 F13
web_search fallback 的 rag/extractor.py + rag/backfill.py 分工）。

over18 cookie：PTT 部分看板需此 cookie 才能存取，一律帶入（不判斷本板是否真的年齡受限）。
robots.txt：實查 https://www.ptt.cc/robots.txt 回 404（不存在＝無限制），本模組本身不做
runtime 檢查，比照既有 5 個來源的作法（manual 驗證，未在程式碼內硬綁 robots 解析器）。
"""

import logging
import re
from collections.abc import Callable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, SoupStrainer

from scraper.http import PoliteClient

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ptt.cc"
BOARD = "Lifeismoney"
INDEX_URL = f"{BASE_URL}/bbs/{BOARD}/index.html"
OVER18_COOKIE_DOMAIN = "www.ptt.cc"

_PAGE_LINK = re.compile(r"index(\d+)\.html")
_TITLE_TAG = "標題"


def build_session() -> requests.Session:
    """帶 over18 cookie 的 session（PTT 部分看板需要才能存取）。"""
    session = requests.Session()
    session.cookies.set("over18", "1", domain=OVER18_COOKIE_DOMAIN)
    return session


def build_client() -> PoliteClient:
    """組好 over18 cookie 的禮貌 client；供 rag/ptt_ingest.py 組裝入口使用。"""
    return PoliteClient(session=build_session())


def list_article_urls(list_html: str) -> list[str]:
    """單一列表頁 → 文章絕對網址（保序、去重）；已被刪除的置底文章沒有 ``<a>``，自然跳過。"""
    soup = BeautifulSoup(list_html, "html.parser", parse_only=SoupStrainer("div", class_="title"))
    urls = []
    for div in soup.find_all("div", class_="title"):
        a = div.find("a")
        if a and a.get("href"):
            urls.append(urljoin(BASE_URL, a["href"]))
    return list(dict.fromkeys(urls))


def fetch_recent_article_urls(get: Callable[[str], str], pages: int = 1) -> list[str]:
    """抓最近 pages 頁（含 index.html 本頁）的文章連結，保序去重；pages < 1 視為 1。

    從 index.html 開始，沿著頁面上的『‹ 上頁』連結往舊頁走；抓到最舊的一頁（該連結
    disabled、無 href）就提早停止，不會因為 pages 設太大而報錯。
    """
    pages = max(pages, 1)
    urls: list[str] = []
    html = get(INDEX_URL)
    urls.extend(list_article_urls(html))
    prev = _prev_page_number(html)
    for _ in range(pages - 1):
        if prev is None:
            break
        html = get(f"{BASE_URL}/bbs/{BOARD}/index{prev}.html")
        urls.extend(list_article_urls(html))
        prev = _prev_page_number(html)
    return list(dict.fromkeys(urls))


def parse_article(article_html: str, url: str) -> str:
    """文章頁 → 原始文本（標題 + 內文，去除 metadata 排版與推文），交給 rag 側 LLM 抽取。

    缺 #main-content 視為版面已改或文章已被刪除，raise ValueError（比照既有來源的
    SKIPPABLE_ERRORS 慣例，由呼叫端記 log 跳過、不中斷整批）。
    """
    soup = BeautifulSoup(article_html, "html.parser")
    main = soup.find(id="main-content")
    if main is None:
        raise ValueError(f"PTT 文章缺 main-content，版面可能已改或文章已被刪除：{url}")

    title = ""
    for meta in main.find_all("div", class_="article-metaline"):
        tag = meta.find("span", class_="article-meta-tag")
        if tag and tag.get_text(strip=True) == _TITLE_TAG:
            value = meta.find("span", class_="article-meta-value")
            title = value.get_text(strip=True) if value else ""
        meta.decompose()
    for meta in main.find_all("div", class_="article-metaline-right"):
        meta.decompose()
    for push in main.find_all("div", class_="push"):
        push.decompose()

    body = main.get_text(separator="\n", strip=True)
    text = f"{title}\n\n{body}".strip() if title else body
    if not text:
        raise ValueError(f"PTT 文章抽不到內文，版面可能已改：{url}")
    return text


def _prev_page_number(list_html: str) -> int | None:
    """從『‹ 上頁』連結解析出上一頁（較舊）的頁碼；連結 disabled（無 href）時回 None。"""
    soup = BeautifulSoup(list_html, "html.parser", parse_only=SoupStrainer("a"))
    for a in soup.find_all("a"):
        href = a.get("href")
        if href and "上頁" in a.get_text():
            match = _PAGE_LINK.search(href)
            if match:
                return int(match.group(1))
    return None
