"""F1: 資料模型 + SQLite schema 測試。

驗收（feature_list.json F1）：
- 可插入/查詢 offer
- offers 表欄位符合 PRD 介面契約（title/content/source_url NOT NULL、valid_to nullable）
- source_url + title 做 upsert key，重複執行不產生重複資料
"""

from datetime import date, datetime

import pytest

from scraper.db import count_offers, init_db, list_offers, upsert_offer
from scraper.models import Offer


@pytest.fixture()
def conn(tmp_path):
    """每個測試一個獨立的臨時 SQLite DB。"""
    connection = init_db(tmp_path / "test_offers.db")
    yield connection
    connection.close()


def make_offer(**overrides) -> Offer:
    """建立合法的測試用 Offer，可覆寫任意欄位。"""
    fields = {
        "source_type": "credit_card",
        "bank": "國泰",
        "provider": None,
        "title": "好市多刷卡 3% 回饋",
        "content": "活動期間於好市多刷國泰卡享 3% 現金回饋，上限 500 元。",
        "channel": "好市多",
        "reward_rate": "3% 現金回饋，上限 500 元",
        "valid_from": date(2026, 7, 1),
        "valid_to": date(2026, 9, 30),
        "source_url": "https://example.com/cathay/costco-3percent",
        "scraped_at": datetime(2026, 7, 8, 12, 0, 0),
    }
    fields.update(overrides)
    return Offer(**fields)


class TestSchema:
    def test_init_db_creates_offers_table(self, conn):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='offers'"
        ).fetchone()
        assert row is not None

    def test_init_db_is_idempotent(self, tmp_path):
        path = tmp_path / "idempotent.db"
        c1 = init_db(path)
        c1.close()
        c2 = init_db(path)  # 第二次不得炸
        c2.close()

    def test_init_db_creates_missing_parent_directory(self, tmp_path):
        """fresh clone 後 data/ 不存在（.gitignore），init_db 要自己建目錄。"""
        path = tmp_path / "data" / "nested" / "offers.db"
        conn = init_db(path)
        conn.close()
        assert path.exists()


class TestInsertAndQuery:
    def test_insert_then_query_returns_same_fields(self, conn):
        offer = make_offer()
        upsert_offer(conn, offer)

        rows = list_offers(conn)
        assert len(rows) == 1
        got = rows[0]
        assert got.title == offer.title
        assert got.content == offer.content
        assert got.bank == "國泰"
        assert got.source_url == offer.source_url
        assert got.valid_to == date(2026, 9, 30)

    def test_valid_to_can_be_null(self, conn):
        """PRD：頁面未標示效期時 valid_to 可為 null。"""
        upsert_offer(conn, make_offer(valid_from=None, valid_to=None))
        assert list_offers(conn)[0].valid_to is None

    def test_e_payment_offer_uses_provider(self, conn):
        offer = make_offer(
            source_type="e_payment",
            bank=None,
            provider="LINE Pay",
            title="超商 LINE Pay 回饋 5%",
            source_url="https://example.com/linepay/cvs",
        )
        upsert_offer(conn, offer)
        assert list_offers(conn)[0].provider == "LINE Pay"


class TestUpsert:
    def test_same_source_url_and_title_does_not_duplicate(self, conn):
        """PRD R1：重複執行不產生重複資料（source_url + title 為 upsert key）。"""
        upsert_offer(conn, make_offer())
        upsert_offer(conn, make_offer(content="內容改版了", reward_rate="5%"))

        assert count_offers(conn) == 1
        got = list_offers(conn)[0]
        assert got.content == "內容改版了"  # 更新而非略過
        assert got.reward_rate == "5%"

    def test_different_title_same_url_creates_new_row(self, conn):
        upsert_offer(conn, make_offer())
        upsert_offer(conn, make_offer(title="另一檔活動"))
        assert count_offers(conn) == 2


class TestValidation:
    """輸入驗證在模型邊界 fail fast（coding rules：validate at system boundaries）。"""

    @pytest.mark.parametrize("field", ["title", "content", "source_url"])
    def test_required_text_fields_reject_empty(self, field):
        with pytest.raises(ValueError, match=field):
            make_offer(**{field: ""})

    def test_source_type_must_be_known(self):
        with pytest.raises(ValueError, match="source_type"):
            make_offer(source_type="lottery")

    def test_credit_card_requires_bank(self):
        """PRD R1：信用卡優惠每筆必含 bank。"""
        with pytest.raises(ValueError, match="bank"):
            make_offer(source_type="credit_card", bank=None)

    def test_e_payment_requires_provider(self):
        """PRD R2：電支優惠 provider 欄位必須標明支付業者。"""
        with pytest.raises(ValueError, match="provider"):
            make_offer(source_type="e_payment", bank=None, provider=None)

    def test_offer_is_immutable(self):
        offer = make_offer()
        with pytest.raises(AttributeError):
            offer.title = "改掉"
