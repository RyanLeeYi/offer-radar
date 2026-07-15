"""Telegram Bot 測試（PRD R7）：假 API client + 假 Update 注入，不打 Telegram 也不打 API。

驗收對應：
- 文字訊息 → 呼叫 POST /query，回 answer + 來源連結
- /start → 使用說明（能問什麼、資料涵蓋範圍、資料更新日）
- 非文字訊息 → 「請用文字提問」
- API 503/504/連線失敗 → 對使用者友善的中文訊息
- 啟動缺 TELEGRAM_BOT_TOKEN → fail fast 明確錯誤
"""

import asyncio
from types import SimpleNamespace

import pytest

from bot.api_client import ApiResult, ApiUnavailableError, OfferRadarClient
from bot.handlers import (
    NON_TEXT_REPLY,
    PROCESSING_REPLY,
    SERVICE_DOWN_REPLY,
    BotHandlers,
    build_start_text,
    format_reply,
)
from bot.main import ensure_token
from config.settings import Settings

QUERY_BODY = {
    "answer": "推薦 Costco 聯名卡，好市多消費 2% 回饋。",
    "sources": [
        {"title": "Costco 聯名卡", "source_url": "https://example.com/costco", "valid_to": "2026-12-31"},
        {"title": "無期限優惠", "source_url": "https://example.com/forever", "valid_to": None},
    ],
}
HEALTH_BODY = {"status": "ok", "offers_count": 228, "last_ingest_at": "2026-07-10T23:42:51+08:00"}


# ---- 純函式：訊息格式 ----


def test_format_reply_includes_answer_and_source_links():
    text = format_reply(QUERY_BODY)
    assert text.startswith("推薦 Costco 聯名卡")
    assert "來源" in text
    assert "https://example.com/costco" in text
    assert "效期至 2026-12-31" in text
    assert "https://example.com/forever" in text


def test_format_reply_without_sources_omits_source_section():
    text = format_reply({"answer": "目前資料庫沒有相關優惠資訊。", "sources": []})
    assert text == "目前資料庫沒有相關優惠資訊。"


def test_format_reply_caps_telegram_message_length():
    body = {"answer": "很長" * 3000, "sources": []}
    assert len(format_reply(body)) <= 4096


def test_build_start_text_mentions_usage_scope_and_data_date():
    text = build_start_text(HEALTH_BODY)
    assert "好市多" in text  # 範例問題（能問什麼）
    assert "國泰" in text and "台新" in text and "富邦" in text  # 資料涵蓋範圍（信用卡）
    assert "街口" in text and "icash Pay" in text  # 資料涵蓋範圍（電子支付，F7）
    assert "2026-07-10" in text  # 資料更新日
    assert "228" in text


def test_build_start_text_survives_health_failure():
    text = build_start_text(None)
    assert "好市多" in text
    assert "未知" in text  # 更新日拿不到時明說，不裝沒事


# ---- API client（注入假 transport，不打網路）----


def test_client_query_posts_question():
    calls = []

    def fake_post(url: str, payload: dict, timeout: float) -> ApiResult:
        calls.append((url, payload, timeout))
        return ApiResult(status=200, body=QUERY_BODY)

    client = OfferRadarClient(base_url="http://localhost:8000", post=fake_post)
    result = client.query("去好市多刷哪張卡最划算")

    assert result == ApiResult(status=200, body=QUERY_BODY)
    url, payload, timeout = calls[0]
    assert url == "http://localhost:8000/query"
    assert payload == {"question": "去好市多刷哪張卡最划算"}
    assert timeout > 90  # API 層 90 秒逾時契約，client 要等得比它久


def test_client_health_gets():
    client = OfferRadarClient(
        base_url="http://localhost:8000/",
        get=lambda url, timeout: ApiResult(status=200, body=HEALTH_BODY),
    )
    assert client.health().body["offers_count"] == 228


# ---- handlers（假 Update / 假 client）----


class FakeSentMessage:
    """reply_text 回傳的訊息物件——記錄後續 edit_text（就地更新「查詢中」→答案）。"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.edits: list[str] = []

    async def edit_text(self, text: str, **kwargs) -> None:
        self.text = text
        self.edits.append(text)


class FakeMessage:
    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.replies: list[str] = []  # 首發訊息（含「查詢中」placeholder）
        self.sent: list[FakeSentMessage] = []

    async def reply_text(self, text: str, **kwargs) -> FakeSentMessage:
        self.replies.append(text)
        sent = FakeSentMessage(text)
        self.sent.append(sent)
        return sent


def make_update(text: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(message=FakeMessage(text=text))


def final_text(update: SimpleNamespace) -> str:
    """使用者最終看到的文字：placeholder 被 edit 後的 .text（沒 edit 就是首發）。"""
    return update.message.sent[-1].text


class FakeClient:
    def __init__(
        self,
        query_result: ApiResult | None = None,
        health_result: ApiResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._query_result = query_result
        self._health_result = health_result or ApiResult(status=200, body=HEALTH_BODY)
        self._error = error
        self.questions: list[str] = []

    def query(self, question: str) -> ApiResult:
        self.questions.append(question)
        if self._error:
            raise self._error
        return self._query_result

    def health(self) -> ApiResult:
        if self._error:
            raise self._error
        return self._health_result


def run(coro):
    return asyncio.run(coro)


def test_on_text_shows_processing_then_edits_to_answer():
    client = FakeClient(query_result=ApiResult(status=200, body=QUERY_BODY))
    handlers = BotHandlers(client)
    update = make_update("去好市多刷哪張卡最划算")

    run(handlers.on_text(update, context=None))

    assert client.questions == ["去好市多刷哪張卡最划算"]
    assert update.message.replies[0] == PROCESSING_REPLY  # 先回「查詢中」，不空等
    reply = final_text(update)  # 就地 edit 成答案，不另開新訊息洗版
    assert "推薦 Costco 聯名卡" in reply
    assert "https://example.com/costco" in reply
    assert update.message.sent[0].edits == [reply]  # 確實是 edit，不是再 reply


def test_on_text_maps_503_to_friendly_message():
    client = FakeClient(query_result=ApiResult(status=503, body={"error": "知識庫尚未建立"}))
    handlers = BotHandlers(client)
    update = make_update("隨便問")

    run(handlers.on_text(update, context=None))

    assert "知識庫尚未建立" in final_text(update)


def test_on_text_maps_504_to_friendly_message():
    client = FakeClient(query_result=ApiResult(status=504, body={"error": "LLM 回應逾時"}))
    handlers = BotHandlers(client)
    update = make_update("隨便問")

    run(handlers.on_text(update, context=None))

    assert "逾時" in final_text(update)


def test_on_text_maps_connection_error_to_service_down():
    client = FakeClient(error=ApiUnavailableError("connection refused"))
    handlers = BotHandlers(client)
    update = make_update("隨便問")

    run(handlers.on_text(update, context=None))

    assert update.message.replies == [PROCESSING_REPLY]  # 只發過 placeholder
    assert final_text(update) == SERVICE_DOWN_REPLY  # 再就地改成錯誤訊息


def test_on_non_text_asks_for_text():
    handlers = BotHandlers(FakeClient())
    update = make_update(text=None)

    run(handlers.on_non_text(update, context=None))

    assert update.message.replies == [NON_TEXT_REPLY]


def test_start_replies_usage():
    handlers = BotHandlers(FakeClient())
    update = make_update("/start")

    run(handlers.start(update, context=None))

    reply = update.message.replies[0]
    assert "好市多" in reply and "2026-07-10" in reply


def test_start_survives_api_down():
    handlers = BotHandlers(FakeClient(error=ApiUnavailableError("down")))
    update = make_update("/start")

    run(handlers.start(update, context=None))

    assert "未知" in update.message.replies[0]


# ---- code review 修正的回歸測試 ----


def test_on_text_maps_422_to_too_long_message():
    client = FakeClient(query_result=ApiResult(status=422, body={"detail": []}))
    handlers = BotHandlers(client)
    update = make_update("超長問題" * 200)

    run(handlers.on_text(update, context=None))

    assert "500" in final_text(update)  # 告訴使用者長度限制，不是籠統的查詢失敗


def test_handlers_ignore_updates_without_message():
    """edited_message / channel_post 的 update.message 是 None——不能炸 AttributeError。"""
    handlers = BotHandlers(FakeClient())
    for handler in (handlers.on_text, handlers.on_non_text, handlers.start):
        run(handler(SimpleNamespace(message=None), context=None))  # 不炸即過


def test_format_reply_hard_caps_even_with_huge_sources():
    body = {
        "answer": "答" * 5000,
        "sources": [
            {"title": "超長標題" * 50, "source_url": "https://example.com/" + "x" * 300, "valid_to": None}
            for _ in range(30)
        ],
    }
    assert len(format_reply(body)) <= 4096


def test_api_errors_are_logged(caplog):
    client = FakeClient(error=ApiUnavailableError("connection refused"))
    handlers = BotHandlers(client)

    with caplog.at_level("WARNING"):
        run(handlers.on_text(make_update("問"), context=None))
        run(handlers.start(make_update("/start"), context=None))

    assert sum("connection refused" in r.message for r in caplog.records) == 2


def test_edited_messages_are_not_dispatched():
    """PTB filter 檢查 effective_message：沒鎖 UpdateType 的話，編輯過的訊息會進 handler。"""
    from datetime import datetime

    from telegram import Chat, Message, Update

    from bot.main import build_application

    app = build_application(Settings(telegram_bot_token="123:abc", _env_file=None))
    edited = Update(
        update_id=1,
        edited_message=Message(
            message_id=1, date=datetime.now(), chat=Chat(id=1, type="private"), text="改過的字"
        ),
    )
    matched = [
        handler
        for group in app.handlers.values()
        for handler in group
        if handler.check_update(edited)
    ]
    assert matched == []


# ---- 啟動 fail fast ----


def test_ensure_token_rejects_empty():
    settings = Settings(telegram_bot_token="", _env_file=None)
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        ensure_token(settings)


def test_ensure_token_passes_through():
    settings = Settings(telegram_bot_token="123:abc", _env_file=None)
    assert ensure_token(settings) == "123:abc"
