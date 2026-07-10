"""Telegram handlers（PRD R7）：文字 → /query、/start → 使用說明、非文字 → 請用文字提問。

blocking 的 requests 呼叫一律 asyncio.to_thread 下放，不佔 PTB 的 event loop。
訊息格式是純函式，測試不用碰 Telegram 物件。
"""

import asyncio
import logging

from bot.api_client import ApiResult, ApiUnavailableError, OfferRadarClient

logger = logging.getLogger(__name__)

TELEGRAM_MESSAGE_LIMIT = 4096
NON_TEXT_REPLY = "請用文字提問"
SERVICE_DOWN_REPLY = "服務暫時無法使用，請稍後再試。"
# API 已定義好的錯誤碼 → 使用者訊息（body.error 是給開發者的，這裡說人話）
_STATUS_REPLIES = {
    422: "問題太長了，請縮短到 500 字以內再問一次。",
    503: "知識庫尚未建立，請先執行資料匯入後再試。",
    504: "回應逾時，請稍後再試（模型可能正在暖機）。",
}
_FALLBACK_REPLY = "查詢失敗，請稍後再試。"


def format_reply(body: dict) -> str:
    """/query 200 的回覆：answer + 來源連結；超限時先犧牲 answer，最後硬切保底。"""
    answer = body["answer"]
    sources = body.get("sources") or []
    if not sources:
        return answer[:TELEGRAM_MESSAGE_LIMIT]

    lines = ["", "來源："]
    for source in sources:
        valid = f"（效期至 {source['valid_to']}）" if source.get("valid_to") else ""
        lines.append(f"- {source['title']}{valid}")
        lines.append(f"  {source['source_url']}")
    tail = "\n".join(lines)
    kept = answer[: max(0, TELEGRAM_MESSAGE_LIMIT - len(tail))]
    return (kept + tail)[:TELEGRAM_MESSAGE_LIMIT]


def build_start_text(health_body: dict | None) -> str:
    """/start 使用說明：能問什麼、資料涵蓋範圍、資料更新日（/health 拿不到就說未知）。"""
    if health_body:
        updated = (health_body.get("last_ingest_at") or "未知")[:10]
        scope = f"目前收錄 {health_body.get('offers_count', '?')} 筆優惠"
    else:
        updated = "未知"
        scope = "收錄筆數暫時查不到"
    return (
        "我是消費優惠比較機器人 🤖\n"
        "直接用一句話問我優惠，例如：\n"
        "・去好市多刷哪張卡最划算\n"
        "・便利商店有什麼行動支付優惠\n\n"
        f"資料涵蓋：國泰、台新、富邦信用卡＋街口、icash Pay 電子支付優惠（{scope}）\n"
        f"資料更新日：{updated}"
    )


class BotHandlers:
    def __init__(self, client: OfferRadarClient) -> None:
        self._client = client

    async def start(self, update, context) -> None:
        if update.message is None:  # edited_message / channel_post 沒有 message
            return
        try:
            health: ApiResult | None = await asyncio.to_thread(self._client.health)
        except ApiUnavailableError as exc:
            logger.warning("health 查詢失敗，/start 以未知回應：%s", exc)
            health = None
        body = health.body if health and health.status == 200 else None
        await update.message.reply_text(build_start_text(body))

    async def on_text(self, update, context) -> None:
        if update.message is None or not update.message.text:
            return
        try:
            result = await asyncio.to_thread(self._client.query, update.message.text)
        except ApiUnavailableError as exc:
            logger.warning("query API 連線失敗：%s", exc)
            await update.message.reply_text(SERVICE_DOWN_REPLY)
            return
        if result.status == 200:
            await update.message.reply_text(format_reply(result.body))
            return
        logger.warning("query API 回 %d：%s", result.status, result.body)
        await update.message.reply_text(_STATUS_REPLIES.get(result.status, _FALLBACK_REPLY))

    async def on_non_text(self, update, context) -> None:
        if update.message is None:
            return
        await update.message.reply_text(NON_TEXT_REPLY)
