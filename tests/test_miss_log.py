"""F11: miss_log 記錄與 24h 防重複測試。

驗收（feature_list.json F11）：
- 查無時把 query 原文 + 時間戳寫入 miss_log，entity 欄位存在且寫入時為 null
- 24h 去重以 entity 為 key；entity 為 null 時退回 raw query
- 跨 24h 邊界後同一 key 可再記一次
- 不依賴 LLM（本檔全程沒有任何 generator/embedding）
"""

from datetime import datetime, timedelta

import pytest

from rag.miss_log import DEDUPE_WINDOW, init_miss_log, list_misses, record_miss
from scraper.db import init_db

NOW = datetime(2026, 8, 22, 10, 0, 0)


@pytest.fixture()
def conn(tmp_path):
    connection = init_db(tmp_path / "offers.db")
    init_miss_log(connection)
    yield connection
    connection.close()


class TestRecord:
    def test_writes_raw_query_timestamp_and_null_entity(self, conn):
        assert record_miss(conn, "全聯有什麼優惠", now=NOW) is True

        rows = conn.execute("SELECT query, entity, created_at FROM miss_log").fetchall()
        assert rows == [("全聯有什麼優惠", None, NOW.isoformat())]

    def test_rejects_blank_query(self, conn):
        with pytest.raises(ValueError):
            record_miss(conn, "   ", now=NOW)

    def test_list_misses_returns_rows_with_entity(self, conn):
        record_miss(conn, "全聯有什麼優惠", now=NOW)
        misses = list_misses(conn)
        assert [(m.query, m.entity) for m in misses] == [("全聯有什麼優惠", None)]
        assert misses[0].created_at == NOW
        assert isinstance(misses[0].id, int)


class TestDedupeByRawQuery:
    """entity 為 null（F11 寫入時的常態）→ 以 raw query 去重。"""

    def test_same_query_within_24h_skipped(self, conn):
        assert record_miss(conn, "全聯有什麼優惠", now=NOW) is True
        assert record_miss(conn, "全聯有什麼優惠", now=NOW + timedelta(hours=5)) is False
        assert len(list_misses(conn)) == 1

    def test_different_query_still_recorded(self, conn):
        record_miss(conn, "全聯有什麼優惠", now=NOW)
        assert record_miss(conn, "家樂福有什麼優惠", now=NOW + timedelta(hours=1)) is True
        assert len(list_misses(conn)) == 2


class TestDedupeByEntity:
    """entity 已回填（F13 正規化之後）→ 以 entity 為 key，不同 raw query 也算重複。"""

    def test_same_entity_different_query_skipped(self, conn):
        assert record_miss(conn, "全聯有什麼優惠", now=NOW, entity="全聯") is True
        assert (
            record_miss(conn, "全聯刷什麼卡划算", now=NOW + timedelta(hours=3), entity="全聯")
            is False
        )
        assert len(list_misses(conn)) == 1

    def test_different_entity_recorded(self, conn):
        record_miss(conn, "全聯有什麼優惠", now=NOW, entity="全聯")
        assert (
            record_miss(conn, "家樂福有什麼優惠", now=NOW + timedelta(hours=3), entity="家樂福")
            is True
        )
        assert len(list_misses(conn)) == 2

    def test_entity_key_ignores_matching_raw_query(self, conn):
        """帶 entity 時就只看 entity：同一句 raw query 但 entity 不同，不算重複。"""
        record_miss(conn, "這家有什麼優惠", now=NOW, entity="全聯")
        assert record_miss(conn, "這家有什麼優惠", now=NOW, entity="家樂福") is True
        assert len(list_misses(conn)) == 2


class TestWindowBoundary:
    def test_just_inside_window_skipped(self, conn):
        record_miss(conn, "全聯有什麼優惠", now=NOW)
        just_inside = NOW + DEDUPE_WINDOW - timedelta(seconds=1)
        assert record_miss(conn, "全聯有什麼優惠", now=just_inside) is False

    def test_exactly_24h_later_recorded(self, conn):
        record_miss(conn, "全聯有什麼優惠", now=NOW)
        assert record_miss(conn, "全聯有什麼優惠", now=NOW + DEDUPE_WINDOW) is True
        assert len(list_misses(conn)) == 2

    def test_entity_window_boundary(self, conn):
        record_miss(conn, "全聯有什麼優惠", now=NOW, entity="全聯")
        assert record_miss(conn, "全聯刷卡", now=NOW + DEDUPE_WINDOW, entity="全聯") is True
        assert len(list_misses(conn)) == 2

    def test_window_is_24_hours(self):
        assert DEDUPE_WINDOW == timedelta(hours=24)


class TestRecorderWiring:
    """build_miss_recorder：每次自己開連線（pipeline 跑在 asyncio.to_thread 的不同執行緒）。"""

    def test_recorder_writes_and_is_thread_safe(self, tmp_path):
        from rag.miss_log import build_miss_recorder

        path = str(tmp_path / "offers.db")
        record = build_miss_recorder(path)

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(record, [f"查詢{i}" for i in range(4)]))

        conn = init_db(path)
        try:
            assert len(list_misses(conn)) == 4
        finally:
            conn.close()

    def test_recorder_never_raises(self, tmp_path):
        """記錄查無是旁路，壞掉不得影響前台查詢。"""
        from rag.miss_log import build_miss_recorder

        record = build_miss_recorder(str(tmp_path / "nope" / "offers.db"))
        record("")  # 空字串會被 record_miss 擋下，但不得往外炸
