"""SQLite 存取層：offers 表的建立、遷移、upsert、查詢。

日期以 ISO 字串儲存，讀出時轉回 date / datetime。
upsert key：UNIQUE(source_url, title)（PRD R1：重複執行不產生重複資料）。
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

from scraper.models import Offer

_SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    bank        TEXT,
    provider    TEXT,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    channel     TEXT,
    reward_rate TEXT,
    valid_from  TEXT,
    valid_to    TEXT,
    source_url  TEXT NOT NULL,
    scraped_at  TEXT NOT NULL,
    trust_tier  TEXT NOT NULL DEFAULT 'verified',
    expires_at  TEXT,
    UNIQUE (source_url, title)
);
"""

# 舊 DB（正式站已有資料）沒有這兩欄：ALTER 補上，既有列吃 DEFAULT 自動成為 verified
_ADDED_COLUMNS = (
    ("trust_tier", "TEXT NOT NULL DEFAULT 'verified'"),
    ("expires_at", "TEXT"),
)

_UPSERT = """
INSERT INTO offers (
    source_type, bank, provider, title, content, channel,
    reward_rate, valid_from, valid_to, source_url, scraped_at, trust_tier, expires_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (source_url, title) DO UPDATE SET
    source_type = excluded.source_type,
    bank        = excluded.bank,
    provider    = excluded.provider,
    content     = excluded.content,
    channel     = excluded.channel,
    reward_rate = excluded.reward_rate,
    valid_from  = excluded.valid_from,
    valid_to    = excluded.valid_to,
    scraped_at  = excluded.scraped_at,
    trust_tier  = excluded.trust_tier,
    expires_at  = excluded.expires_at;
"""

_SELECT_COLUMNS = (
    "source_type, bank, provider, title, content, channel, "
    "reward_rate, valid_from, valid_to, source_url, scraped_at, trust_tier, expires_at"
)


def init_db(path: str | Path) -> sqlite3.Connection:
    """開啟（必要時建立）資料庫並確保 schema 存在。可重複呼叫。

    父目錄不存在時自動建立（data/ 在 .gitignore，fresh clone 後不存在）。
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    _add_missing_columns(conn)
    conn.commit()
    return conn


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """把 _ADDED_COLUMNS 補進舊 schema 的 offers 表（新建的表已有，直接略過）。"""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(offers)")}
    for name, definition in _ADDED_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE offers ADD COLUMN {name} {definition}")


def upsert_offer(conn: sqlite3.Connection, offer: Offer) -> None:
    """寫入一筆優惠；(source_url, title) 已存在時更新其餘欄位。

    不自行 commit——transaction 邊界由 caller 控制（批量入庫時整批一個 transaction）。
    """
    conn.execute(
        _UPSERT,
        (
            offer.source_type,
            offer.bank,
            offer.provider,
            offer.title,
            offer.content,
            offer.channel,
            offer.reward_rate,
            offer.valid_from.isoformat() if offer.valid_from else None,
            offer.valid_to.isoformat() if offer.valid_to else None,
            offer.source_url,
            offer.scraped_at.isoformat(),
            offer.trust_tier,
            offer.expires_at.isoformat() if offer.expires_at else None,
        ),
    )


def list_offers(conn: sqlite3.Connection) -> list[Offer]:
    """讀出所有優惠（轉回 Offer 物件）。"""
    rows = conn.execute(f"SELECT {_SELECT_COLUMNS} FROM offers ORDER BY id").fetchall()
    return [_row_to_offer(row) for row in rows]


def count_offers(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0]


def list_active_offers(
    conn: sqlite3.Connection, today: date, now: datetime | None = None
) -> list[tuple[int, Offer]]:
    """讀出仍有效的優惠連同 id——RAG ingest 的資料來源（PRD R3）。

    兩道獨立過濾：``valid_to`` 是優惠本身的效期（日），``expires_at`` 是 web_unverified
    資料的 TTL（時間戳，F12）——爬蟲來源沒有 TTL，第二道對它們永遠成立。
    日期／時間都以 ISO 字串儲存，字典序即時序，可直接用字串比較。
    """
    now = now or datetime.now()
    rows = conn.execute(
        f"SELECT id, {_SELECT_COLUMNS} FROM offers "
        "WHERE (valid_to IS NULL OR valid_to >= ?) "
        "AND (expires_at IS NULL OR expires_at > ?) ORDER BY id",
        (today.isoformat(), now.isoformat()),
    ).fetchall()
    return [(row[0], _row_to_offer(row[1:])) for row in rows]


def _row_to_offer(row: tuple) -> Offer:
    (
        source_type, bank, provider, title, content, channel,
        reward_rate, valid_from, valid_to, source_url, scraped_at,
        trust_tier, expires_at,
    ) = row
    return Offer(
        source_type=source_type,
        bank=bank,
        provider=provider,
        title=title,
        content=content,
        channel=channel,
        reward_rate=reward_rate,
        valid_from=date.fromisoformat(valid_from) if valid_from else None,
        valid_to=date.fromisoformat(valid_to) if valid_to else None,
        source_url=source_url,
        scraped_at=datetime.fromisoformat(scraped_at),
        trust_tier=trust_tier,
        expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
    )
