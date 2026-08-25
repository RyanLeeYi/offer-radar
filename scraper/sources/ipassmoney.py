"""iPASS 一卡通官網 News 公告：純爬取（F22）。

只負責「列表頁 → 文章連結 → 文章原始文本」，不碰 LLM 抽取、不碰 DB——兩者由
``rag/ipass_extractor.py``、``rag/ipass_ingest.py`` 負責（scraper/ 不得 import rag/），
分工比照 F21 PTT 三件組（scraper/sources/lifeismoney.py）。

robots.txt：實查 https://www.i-pass.com.tw/robots.txt 回傳站內「找不到資料」頁（非真正
的 robots 規則檔，等同不存在），本模組本身不做 runtime 檢查，比照既有來源的作法（manual
驗證，未在程式碼內硬綁 robots 解析器）。

分頁：`/News?page=N`（page=1 即 `/News` 本身），頁碼可預測，不需像 PTT 那樣沿『上頁』
連結走訪。
"""

import logging
from collections.abc import Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup, SoupStrainer

logger = logging.getLogger(__name__)

BASE_URL = "https://www.i-pass.com.tw"
NEWS_URL = f"{BASE_URL}/News"


def _page_url(page: int) -> str:
    return NEWS_URL if page <= 1 else f"{NEWS_URL}?page={page}"


def list_article_urls(list_html: str) -> list[str]:
    """單一列表頁 → 文章絕對網址（保序、去重）。"""
    soup = BeautifulSoup(
        list_html, "html.parser", parse_only=SoupStrainer("div", class_="news-listpost")
    )
    urls = []
    for div in soup.find_all("div", class_="news-listpost"):
        h3 = div.find("h3")
        a = h3.find("a") if h3 else None
        if a and a.get("href"):
            urls.append(urljoin(BASE_URL, a["href"]))
    return list(dict.fromkeys(urls))


def fetch_recent_article_urls(get: Callable[[str], str], pages: int = 1) -> list[str]:
    """抓最近 pages 頁（page=1..pages）的文章連結，保序去重；pages < 1 視為 1。

    某頁抓不到任何文章連結（超出實際頁數）就提早停止，不會因為 pages 設太大而報錯。
    """
    pages = max(pages, 1)
    urls: list[str] = []
    for page in range(1, pages + 1):
        page_urls = list_article_urls(get(_page_url(page)))
        if not page_urls:
            break
        urls.extend(page_urls)
    return list(dict.fromkeys(urls))


def parse_article(article_html: str, url: str) -> str:
    """文章頁 → 原始文本（標題 + 內文，去除分享按鈕與 script），交給 rag 側 LLM 抽取。

    缺 .article-post 視為版面已改或文章已下架，raise ValueError（比照既有來源的
    SKIPPABLE_ERRORS 慣例，由呼叫端記 log 跳過、不中斷整批）。
    """
    soup = BeautifulSoup(article_html, "html.parser")
    article = soup.find("div", class_="article-post")
    if article is None:
        raise ValueError(f"iPASS 文章缺 article-post，版面可能已改或文章已下架：{url}")

    title_tag = article.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else ""
    if title_tag is not None:
        title_tag.decompose()
    for tag in article.find_all(["script", "noscript"]):
        tag.decompose()
    post_repo = article.find("div", class_="post-repo")
    if post_repo is not None:
        post_repo.decompose()

    body = article.get_text(separator="\n", strip=True)
    text = f"{title}\n\n{body}".strip() if title else body
    if not text:
        raise ValueError(f"iPASS 文章抽不到內文，版面可能已改：{url}")
    return text
