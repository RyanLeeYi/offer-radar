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
    expires_at  = excluded.expires_at
WHERE NOT (offers.trust_tier = 'verified' AND excluded.trust_tier != 'verified');
"""

_SELECT_COLUMNS = (
    "source_type, bank, provider, title, content, channel, "
    "reward_rate, valid_from, valid_to, source_url, scraped_at, trust_tier, expires_at"
)

# 獨立於 miss_log 的表：只記「entity 上次實際發出搜尋的時間」，供背景補查 job（F15）
# 24h 去重使用。不用 miss_log.created_at 近似，因為那是「miss 被記下來的時間」，
# 被讀取 limit 擋在處理佇列外的 miss 可能拖很久才真正觸發搜尋，兩者會脫節（F19）。
_SEARCH_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_log (
    entity      TEXT PRIMARY KEY,
    searched_at TEXT NOT NULL
);
"""


def init_db(path: str | Path) -> sqlite3.Connection:
    """開啟（必要時建立）資料庫並確保 schema 存在。可重複呼叫。

    父目錄不存在時自動建立（data/ 在 .gitignore，fresh clone 後不存在）。
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    _add_missing_columns(conn)
    conn.execute(_SEARCH_LOG_SCHEMA)
    conn.commit()
    return conn


def init_search_log(conn: sqlite3.Connection) -> None:
    """確保 search_log 表存在。可重複呼叫（``init_db`` 也會建，這裡給只有 conn 沒有
    path 的呼叫端，如 ``rag.backfill.backfill`` 用）。"""
    conn.execute(_SEARCH_LOG_SCHEMA)
    conn.commit()


def record_search(conn: sqlite3.Connection, entity: str, when: datetime) -> None:
    """記錄 entity 剛發出了一次實際搜尋。24h 去重判準只看這份記錄，不受讀取 limit 影響。"""
    conn.execute(
        "INSERT INTO search_log (entity, searched_at) VALUES (?, ?) "
        "ON CONFLICT (entity) DO UPDATE SET searched_at = excluded.searched_at",
        (entity, when.isoformat()),
    )
    conn.commit()


def recently_searched(conn: sqlite3.Connection, since: datetime) -> set[str]:
    """回傳 since 之後（不含）實際發出過搜尋的 entity 集合。"""
    rows = conn.execute(
        "SELECT entity FROM search_log WHERE searched_at > ?", (since.isoformat(),)
    ).fetchall()
    return {row[0] for row in rows}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """把 _ADDED_COLUMNS 補進舊 schema 的 offers 表（新建的表已有，直接略過）。"""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(offers)")}
    for name, definition in _ADDED_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE offers ADD COLUMN {name} {definition}")


def upsert_offer(conn: sqlite3.Connection, offer: Offer) -> None:
    """寫入一筆優惠；(source_url, title) 已存在時更新其餘欄位。

    不自行 commit——transaction 邊界由 caller 控制（批量入庫時整批一個 transaction）。

    **非 verified 資料不得覆蓋 verified**：upsert key 是 (source_url, title)，網搜或
    LLM fallback 補來的資料若撞上爬蟲已收的同一筆，覆蓋會把可信資料降級（web_unverified
    還會多掛 7 天 TTL，到期後連原本的爬蟲資料都會被 list_active_offers 濾掉）。這道
    WHERE 擋在所有寫入者共用的路徑上，且不逐一列舉非 verified 的 tier 名稱（F23 新增
    llm_fallback 時不必再改一次這條 SQL）。
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
