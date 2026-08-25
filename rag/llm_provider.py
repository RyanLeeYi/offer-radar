"""LLM provider 選擇、``<think>`` 剝除與逾時常數的單一事實來源。

``rag/llm.py``（通用 completion）與 ``rag/generator.py``（檢索問答生成器）各自要打
ollama／openai，provider 選擇與 fail-fast 規則完全相同（未知或缺金鑰一律 fail
fast），因此在此共用同一個 factory，避免兩處各維護一份而漂移。
"""

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from config.settings import Settings

THINK_TAG = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
# 冷載入 8B 模型實測約 24 秒 + 生成時間；PRD 的 30 秒逾時是 API 層（F5）的契約，
# transport 層放寬到 120 秒讓冷啟動活得下來
TIMEOUT = 120.0

T = TypeVar("T")


def select_provider(
    settings: "Settings", build_ollama: Callable[[], T], build_openai: Callable[[], T]
) -> T:
    """依 ``settings.llm_provider`` 選擇並建構對應實作；openai 缺金鑰或未知 provider 一律 fail fast。"""
    provider = settings.llm_provider.lower()
    if provider == "ollama":
        return build_ollama()
    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "LLM_PROVIDER=openai 需要 OPENAI_API_KEY，請在 .env 或環境變數設定後再啟動"
            )
        return build_openai()
    raise ValueError(f"未知的 LLM_PROVIDER：{settings.llm_provider!r}（可用 ollama 或 openai）")
