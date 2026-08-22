"""查無（miss）記錄：把答不出來的 query 原文與時間戳留下來，供背景補查 job 消化。

與 offers 共用同一個 SQLite 檔，另開一張 miss_log 表。``entity``（品牌/通路）寫入時為
null——本模組不碰 LLM，正規化回填是 F13 的事。24h 去重以 entity 為 key，entity 尚未
回填時退回 raw query，避免同一件事重複觸發網搜（設計見
docs/superpowers/specs/2026-07-12-web-search-fallback-design.md）。
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from sqlite3 import Connection

from scraper.db import init_db

logger = logging.getLogger(__name__)

DEDUPE_WINDOW = timedelta(hours=24)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS miss_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    query      TEXT NOT NULL,
    entity     TEXT,
    created_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Miss:
    id: int
    query: str
    entity: str | None
    created_at: datetime


def init_miss_log(conn: Connection) -> None:
    """確保 miss_log 表存在。可重複呼叫。"""
    conn.execute(_SCHEMA)
    conn.commit()


def record_miss(
    conn: Connection, query: str, now: datetime, entity: str | None = None
) -> bool:
    """記一筆查無；24h 內同一 key 已記過則跳過。有寫入回 True，跳過回 False。

    去重 key：有 entity 就只看 entity（不同問法算同一件事），沒有就看 raw query。
    邊界採「嚴格小於 24 小時內才算重複」——剛好滿 24h 可再記一次。
    """
    query = query.strip()
    if not query:
        raise ValueError("query 不得為空")
    since = (now - DEDUPE_WINDOW).isoformat()
    if entity:
        duplicate = conn.execute(
            "SELECT 1 FROM miss_log WHERE entity = ? AND created_at > ? LIMIT 1",
            (entity, since),
        )
    else:
        duplicate = conn.execute(
            "SELECT 1 FROM miss_log WHERE query = ? AND created_at > ? LIMIT 1",
            (query, since),
        )
    if duplicate.fetchone():
        return False
    conn.execute(
        "INSERT INTO miss_log (query, entity, created_at) VALUES (?, ?, ?)",
        (query, entity, now.isoformat()),
    )
    conn.commit()
    return True


def set_entity(conn: Connection, miss_id: int, entity: str) -> None:
    """回填查詢正規化抽出的 entity（F13 產出，F15 背景 job 收尾時呼叫）。"""
    conn.execute("UPDATE miss_log SET entity = ? WHERE id = ?", (entity, miss_id))
    conn.commit()


def list_misses(conn: Connection) -> list[Miss]:
    """讀出所有查無記錄（背景補查 job 的資料來源，也是「下一個爬蟲寫誰」的需求數據）。"""
    rows = conn.execute(
        "SELECT id, query, entity, created_at FROM miss_log ORDER BY id"
    ).fetchall()
    return [Miss(r[0], r[1], r[2], datetime.fromisoformat(r[3])) for r in rows]


def build_miss_recorder(database_path: str | Path):
    """做出一個 ``(question) -> None`` 的記錄函式給 pipeline 用。

    每次自己開關連線：pipeline 由 ``asyncio.to_thread`` 呼叫，每次執行緒不同，
    sqlite3 連線不能跨執行緒共用。查無本來就罕見，一次連線的成本無所謂。
    記錄失敗只 log 不外拋——這是旁路，不該讓使用者的查詢跟著壞掉。
    """

    def record(question: str) -> None:
        try:
            conn = init_db(database_path)
            try:
                init_miss_log(conn)
                record_miss(conn, question, datetime.now())
            finally:
                conn.close()
        except Exception:
            logger.exception("寫入 miss_log 失敗（不影響本次查詢）：%r", question)

    return record
