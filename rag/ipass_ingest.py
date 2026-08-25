"""iPASS 一卡通 News 爬蟲 + LLM 抽取入庫組裝入口（F22）。

``python -m rag.ipass_ingest`` 手動執行：爬列表頁近 N 頁 → 逐篇抓內文 → LLM 抽取 →
通過 schema 驗證才入庫。單篇失敗只記 log 跳過，不中斷整批（設計比照 rag/ptt_ingest.py）。

這一輪不掛進 scraper/runner.py 的固定跑批清單，理由同 F21：正式接線入口留待下一輪。
"""

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Connection

from config.settings import Settings
from rag.ipass_extractor import Article, extract_offers
from rag.llm import LlmFn, build_completion
from scraper.db import init_db, upsert_offer
from scraper.http import PoliteClient
from scraper.sources._shared import SKIPPABLE_ERRORS
from scraper.sources.ipassmoney import fetch_recent_article_urls, parse_article

logger = logging.getLogger(__name__)

DEFAULT_PAGES = 1


@dataclass(frozen=True)
class IngestResult:
    fetched: int  # 成功抓到並解析出原始文本的文章數
    stored: int  # 通過 LLM 抽取與 schema 驗證、寫進 offers 的筆數


def ingest_ipassmoney(
    conn: Connection,
    get: Callable[[str], str],
    complete: LlmFn,
    now: datetime,
    pages: int = DEFAULT_PAGES,
) -> IngestResult:
    """列表頁近 pages 頁 → 逐篇抓內文 → LLM 抽取 → 入庫。單篇失敗只記 log 跳過，不中斷整批。"""
    urls = fetch_recent_article_urls(get, pages)
    articles: list[Article] = []
    for url in urls:
        try:
            articles.append(Article(url=url, text=parse_article(get(url), url)))
        except SKIPPABLE_ERRORS as error:
            logger.warning("iPASS 文章抓取失敗，跳過：%s（%s）", url, error)

    offers = extract_offers(articles, complete, now)
    for offer in offers:
        upsert_offer(conn, offer)
    conn.commit()
    return IngestResult(fetched=len(articles), stored=len(offers))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings()
    complete = build_completion(settings)
    conn = init_db(settings.database_path)
    try:
        result = ingest_ipassmoney(conn, PoliteClient().get_text, complete, datetime.now())
    finally:
        conn.close()
    print(f"fetched={result.fetched} stored={result.stored}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
