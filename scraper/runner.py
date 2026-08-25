"""爬蟲入口共用 runner：來源隔離執行、transaction 邊界、CLI 收尾（PRD R1/R2 行為契約）。

- 各來源依序執行、彼此隔離
- 某來源失敗（例外或抓到 0 筆）→ log ERROR、其他來源照常、exit code 1
- 既有資料一律保留（只 upsert，不清空）；一個來源一個 transaction
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from sqlite3 import Connection

from config.settings import Settings
from scraper.db import init_db, upsert_offer
from scraper.http import PoliteClient
from scraper.models import Offer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Source:
    """一個優惠來源：name 用於 log 與失敗回報，fetch 回傳整批 Offer。"""

    name: str
    fetch: Callable[[], list[Offer]]


def run(sources: list[Source], conn: Connection) -> int:
    """執行所有來源並入庫；任一來源失敗回 1（其他來源仍完成），全成功回 0。"""
    failed: list[str] = []
    for source in sources:
        try:
            offers = source.fetch()
            if not offers:
                logger.error("來源 %s 抓到 0 筆，視為失敗（版面可能已改）", source.name)
                failed.append(source.name)
                continue
            for offer in offers:
                upsert_offer(conn, offer)
            conn.commit()  # 一個來源一個 transaction：整批成功才落盤
        except Exception:
            conn.rollback()  # 失敗來源整批不落盤，避免半批資料混進下一個來源的 commit
            logger.exception("來源 %s 爬取或入庫失敗，既有資料保留", source.name)
            failed.append(source.name)
            continue
        logger.info("來源 %s 入庫 %d 筆", source.name, len(offers))
    return 1 if failed else 0


def cli_main(build_sources: Callable[[Callable[[str], str]], list[Source]]) -> int:
    """CLI 入口共用流程：logging、DB 路徑（走 config.settings，OFFER_RADAR_DB 可覆寫）、收尾關連線。"""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    conn = init_db(Settings().database_path)
    try:
        return run(build_sources(PoliteClient().get_text), conn)
    finally:
        conn.close()
