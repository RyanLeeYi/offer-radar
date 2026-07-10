"""Telegram Bot 進入點：``python -m bot.main``（long polling）。

啟動前置：ollama serve → uvicorn api.main:app → 本模組。
缺 TELEGRAM_BOT_TOKEN 直接 fail fast（PRD R6 同款精神：啟動就炸，不是收訊息才炸）。
"""

import logging
import sys

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.api_client import OfferRadarClient
from bot.handlers import BotHandlers
from config.settings import Settings

logger = logging.getLogger(__name__)


def ensure_token(settings: Settings) -> str:
    if not settings.telegram_bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN 未設定：請在 .env 加入 TELEGRAM_BOT_TOKEN=<BotFather 發的 token>"
        )
    return settings.telegram_bot_token


def build_application(settings: Settings) -> Application:
    logger.info("API base url：%s", settings.api_base_url)
    client = OfferRadarClient(base_url=settings.api_base_url)
    handlers = BotHandlers(client)
    application = Application.builder().token(ensure_token(settings)).build()
    # 鎖 UpdateType.MESSAGE：filters 檢查的是 effective_message，不鎖的話
    # edited_message / channel_post 也會進 handler（其 update.message 是 None）
    new_message = filters.UpdateType.MESSAGE & ~filters.COMMAND
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(MessageHandler(new_message & filters.TEXT, handlers.on_text))
    application.add_handler(MessageHandler(new_message & ~filters.TEXT, handlers.on_non_text))
    return application


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        application = build_application(Settings())
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1
    logger.info("bot 啟動，開始 polling（Ctrl+C 停止）")
    application.run_polling()
    return 0


if __name__ == "__main__":
    sys.exit(main())
