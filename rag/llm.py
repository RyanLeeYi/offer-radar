"""通用 LLM 補全：F13 查詢正規化與結構化抽取共用的 ``(prompt) -> 回覆文字`` 介面。

與 ``rag/generator.py`` 的差異：generator 是「檢索結果 + 問題」固定 prompt 配方的
回答生成器；這裡是給任意 prompt 用的通用 completion，供 ``rag/extractor.py`` 的
查詢正規化與網搜結果抽取兩步驟共用，不綁定 generator 那組窄簽名。
provider 選擇、fail-fast 邏輯與 ``<think>`` 剝除均與 generator.py 共用同一份定義
（見 ``rag/llm_provider.py``），避免兩處各自維護一份而漂移。
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

import requests

from rag.llm_provider import THINK_TAG, TIMEOUT, select_provider

if TYPE_CHECKING:
    from config.settings import Settings

LlmFn = Callable[[str], str]


def _ollama_complete(base_url: str, model: str) -> LlmFn:
    url = f"{base_url.rstrip('/')}/api/chat"

    def complete(prompt: str) -> str:
        payload = {
            "model": model,
            "stream": False,
            "think": False,
            "options": {"num_ctx": 8192},
            "messages": [{"role": "user", "content": prompt}],
        }
        response = requests.post(url, json=payload, timeout=TIMEOUT)
        response.raise_for_status()
        reply = response.json()["message"]["content"]
        return THINK_TAG.sub("", reply).strip()

    return complete


def _openai_complete(model: str, api_key: str) -> LlmFn:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=TIMEOUT)

    def complete(prompt: str) -> str:
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}]
        )
        reply = response.choices[0].message.content or ""
        return THINK_TAG.sub("", reply).strip()

    return complete


def build_completion(settings: "Settings") -> LlmFn:
    """依 ``settings.llm_provider`` 選 completion 函式；openai 缺金鑰或未知 provider 即 fail fast。"""
    return select_provider(
        settings,
        lambda: _ollama_complete(settings.ollama_base_url, settings.ollama_model),
        lambda: _openai_complete(settings.openai_model, settings.openai_api_key),
    )
