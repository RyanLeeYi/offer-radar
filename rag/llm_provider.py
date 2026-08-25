"""LLM provider 選擇、``<think>`` 剝除與逾時常數的單一事實來源。

``rag/llm.py``（通用 completion）與 ``rag/generator.py``（檢索問答生成器）各自要打
ollama／openai／claude，provider 選擇與 fail-fast 規則完全相同（未知、缺金鑰或
CLI 缺失一律 fail fast），因此在此共用同一個 factory，避免多處各維護一份而漂移。

claude provider（F24）：無頭呼叫本機已登入的 Claude Code CLI（``claude -p``），走訂閱
帳號、不需 API key。CLI 缺失可在建構期以 ``shutil.which`` 檢查、與 openai 缺金鑰同一
時機 fail fast；「未登入」無法不真的呼叫就得知，留給 ``claude_complete`` 在首次查詢時
以 CLI 的非零結束碼與 stderr 組出可讀錯誤。
"""

import re
import shutil
import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from config.settings import Settings

THINK_TAG = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
# 冷載入 8B 模型實測約 24 秒 + 生成時間；PRD 的 30 秒逾時是 API 層（F5）的契約，
# transport 層放寬到 120 秒讓冷啟動活得下來
TIMEOUT = 120.0

T = TypeVar("T")

RunFn = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _run_claude_cli(args: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT, check=False
    )


def claude_complete(prompt: str, run: RunFn = _run_claude_cli) -> str:
    """呼叫本機已登入的 claude CLI（無頭模式，``claude -p``）取得回覆原文。

    回傳未剝除 ``<think>`` 的原始文字——與 ollama/openai 同一套模式，剝除交由呼叫端
    （見 ``rag/llm.py``、``rag/generator.py``）。``run`` 可注入，供測試用假 subprocess。
    """
    result = run(["claude", "-p", prompt, "--output-format", "text"])
    if result.returncode != 0:
        raise RuntimeError(
            "claude CLI 執行失敗，請確認已執行 `claude login` 登入 Claude 訂閱帳號："
            f"{result.stderr.strip()}"
        )
    return result.stdout


def select_provider(
    settings: "Settings",
    build_ollama: Callable[[], T],
    build_openai: Callable[[], T],
    build_claude: Callable[[], T],
) -> T:
    """依 ``settings.llm_provider`` 選擇並建構對應實作；openai 缺金鑰、claude CLI 缺失或
    未知 provider 一律 fail fast。"""
    provider = settings.llm_provider.lower()
    if provider == "ollama":
        return build_ollama()
    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "LLM_PROVIDER=openai 需要 OPENAI_API_KEY，請在 .env 或環境變數設定後再啟動"
            )
        return build_openai()
    if provider == "claude":
        if shutil.which("claude") is None:
            raise ValueError(
                "LLM_PROVIDER=claude 需要本機安裝並登入 claude CLI（執行 `claude login`），"
                "找不到 claude 執行檔，請確認已安裝並在 PATH 中"
            )
        return build_claude()
    raise ValueError(
        f"未知的 LLM_PROVIDER：{settings.llm_provider!r}（可用 ollama、openai 或 claude）"
    )
