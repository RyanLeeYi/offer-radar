"""信用卡爬蟲入口：``python -m scraper.credit_card``（PRD R1）。

行為契約：
- 三來源（國泰、台新、富邦）依序執行，彼此隔離
- 某來源失敗（例外或抓到 0 筆）→ log ERROR、其他來源照常、exit code 1
- 既有資料一律保留（只 upsert，不清空）
"""

import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from sqlite3 import Connection

from scraper.db import init_db, upsert_offer
from scraper.http import PoliteClient
from scraper.models import Offer
from scraper.sources import cathay, fubon, taishin

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "data/offers.db"


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
        except Exception:
            logger.exception("來源 %s 爬取失敗，既有資料保留", source.name)
            failed.append(source.name)
            continue
        if not offers:
            logger.error("來源 %s 抓到 0 筆，視為失敗（版面可能已改）", source.name)
            failed.append(source.name)
            continue
        for offer in offers:
            upsert_offer(conn, offer)
        conn.commit()  # 一個來源一個 transaction：整批成功才落盤
        logger.info("來源 %s 入庫 %d 筆", source.name, len(offers))
    return 1 if failed else 0


def build_sources(get: Callable[[str], str]) -> list[Source]:
    return [
        Source(name="cathay", fetch=lambda: cathay.fetch(get)),
        Source(name="taishin", fetch=lambda: taishin.fetch(get)),
        Source(name="fubon", fetch=lambda: fubon.fetch(get)),
    ]


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    db_path = os.environ.get("OFFER_RADAR_DB", DEFAULT_DB_PATH)
    conn = init_db(db_path)
    try:
        return run(build_sources(PoliteClient().get_text), conn)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
