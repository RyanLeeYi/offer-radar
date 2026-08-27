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

import requests

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


# 健康預檢預算（F25）：模型已載入時吐 1 個 token 實測 <1 秒；5 秒還沒回就是主機在 thrash
# （VRAM/RAM 不足退回 CPU），沒必要讓使用者空等 QUERY_TIMEOUT_SECONDS 的 90 秒。
# ponytail: 這兩個常數就是校準旋鈕——換主機或換模型覺得誤殺，調這裡
HEALTH_TIMEOUT = 5.0
# /api/ps 給得比探測寬，因為它判的是「daemon 在不在」而不是「跑得快不快」，而 daemon
# 不在時是 connection refused、秒回，根本用不到這個上限——它只擋「有人監聽但不回話」。
# 給 10 秒是因為預設的 http://localhost:11434 在 Windows 上每次要 2.0 秒（先試 IPv6
# ::1、closed 端點等約 2 秒才 fallback 到 IPv4；同一支 API 走 127.0.0.1 只要 0.016 秒，
# 2026/08/27 實測）。原本抓 3 秒只剩不到 1 秒餘裕，主機一忙就會誤報「連不上 ollama」——
# 偏偏主機忙正是這道預檢要處理的情境，誤殺比它想修的 bug 更糟。
PS_TIMEOUT = 10.0


class ProviderUnavailable(RuntimeError):
    """LLM provider 現在實質不可用。

    訊息寫成給使用者看的繁中句子——api/main.py 會原樣放進 /query 的 error 欄位。
    """


GetJsonFn = Callable[[str, float], dict]
PostJsonFn = Callable[[str, dict, float], dict]


def _get_json(url: str, timeout: float) -> dict:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def check_ollama(
    base_url: str,
    model: str,
    get: GetJsonFn = _get_json,
    post: PostJsonFn = _post_json,
) -> None:
    """查詢前確認 ollama 能即時產出 token，不行就 raise ProviderUnavailable（F25）。

    先看 ``/api/ps`` 而不是直接探測：模型還沒載入時，探測本身會觸發冷載入（8B 實測約
    24 秒），用短預算去探等於誤殺正常的冷啟動。**已載入卻連一個 token 都吐不出來**，
    才是真的病了——2026/08/25 實測就是這個形狀（qwen3:8b 被排成 94% CPU，可用 RAM
    只剩 643MB，/query 空等滿 90 秒才回 504）。

    transport 可注入，測試不打網路。
    """
    base = base_url.rstrip("/")
    try:
        running = get(f"{base}/api/ps", PS_TIMEOUT).get("models", [])
    except requests.RequestException as exc:
        raise ProviderUnavailable(
            f"連不上 ollama 服務（{base}），請確認 `ollama serve` 已啟動後再試"
        ) from exc
    if not any(model in (entry.get("model"), entry.get("name")) for entry in running):
        return  # 冷啟動：慢是正常的，交給正式查詢自己等
    try:
        post(
            f"{base}/api/generate",
            {
                "model": model,
                "prompt": "hi",
                "stream": False,
                "think": False,
                "options": {"num_predict": 1},
            },
            HEALTH_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ProviderUnavailable(
            f"ollama 模型 {model} 已載入，卻無法在 {HEALTH_TIMEOUT:.0f} 秒內產出 token，"
            "可能是記憶體不足退回 CPU 執行；請稍後再試，或先釋放主機記憶體"
        ) from exc
