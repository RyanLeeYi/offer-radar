"""信用卡爬蟲入口（orchestrator）測試：PRD R1 錯誤行為。

- 某來源失敗 → log ERROR、其他來源照常入庫、exit code 非 0
- 來源回空清單視同失敗（版面改版的沉默失敗防護）
- 全部成功 → exit code 0
"""

import logging
from datetime import datetime

from scraper.credit_card import Source, run
from scraper.db import count_offers, init_db, list_offers
from scraper.models import Offer

SCRAPED_AT = datetime(2026, 7, 10, 12, 0, 0)


def make_offer(title: str) -> Offer:
    return Offer(
        source_type="credit_card",
        bank="測試銀行",
        provider=None,
        title=title,
        content=f"{title} 的內容",
        channel=None,
        reward_rate=None,
        valid_from=None,
        valid_to=None,
        source_url=f"https://example.com/{title}",
        scraped_at=SCRAPED_AT,
    )


def test_all_sources_ok_returns_zero(tmp_path):
    conn = init_db(tmp_path / "offers.db")
    sources = [
        Source(name="a", fetch=lambda: [make_offer("優惠A")]),
        Source(name="b", fetch=lambda: [make_offer("優惠B"), make_offer("優惠C")]),
    ]
    assert run(sources, conn) == 0
    assert count_offers(conn) == 3


def test_failed_source_logs_error_and_keeps_others(tmp_path, caplog):
    conn = init_db(tmp_path / "offers.db")

    def boom() -> list[Offer]:
        raise RuntimeError("網站改版了")

    sources = [
        Source(name="broken", fetch=boom),
        Source(name="ok", fetch=lambda: [make_offer("倖存優惠")]),
    ]
    with caplog.at_level(logging.ERROR):
        exit_code = run(sources, conn)

    assert exit_code != 0
    assert any("broken" in r.message for r in caplog.records if r.levelno == logging.ERROR)
    assert [o.title for o in list_offers(conn)] == ["倖存優惠"]


def test_failed_source_preserves_existing_rows(tmp_path):
    conn = init_db(tmp_path / "offers.db")
    ok = [Source(name="a", fetch=lambda: [make_offer("既有優惠")])]
    assert run(ok, conn) == 0

    def boom() -> list[Offer]:
        raise RuntimeError("boom")

    assert run([Source(name="a", fetch=boom)], conn) != 0
    assert [o.title for o in list_offers(conn)] == ["既有優惠"]  # 不清空


def test_upsert_does_not_commit_run_commits_per_source(tmp_path):
    """transaction 邊界由 run() 控制：來源完整入庫才 commit，別的連線才看得到。"""
    import sqlite3

    db_path = tmp_path / "offers.db"
    conn = init_db(db_path)
    from scraper.db import upsert_offer

    upsert_offer(conn, make_offer("未提交優惠"))
    other = sqlite3.connect(db_path)
    assert other.execute("SELECT COUNT(*) FROM offers").fetchone()[0] == 0  # 尚未 commit

    assert run([Source(name="a", fetch=lambda: [make_offer("已提交優惠")])], conn) == 0
    visible = other.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    assert visible == 2  # run() 收尾 commit，連同先前未提交的一起落盤
    other.close()


def test_empty_result_counts_as_failure(tmp_path, caplog):
    conn = init_db(tmp_path / "offers.db")
    sources = [Source(name="hollow", fetch=lambda: [])]
    with caplog.at_level(logging.ERROR):
        assert run(sources, conn) != 0
    assert any("hollow" in r.message for r in caplog.records if r.levelno == logging.ERROR)
