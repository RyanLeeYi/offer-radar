"""生成：把檢索到的 context + 問題組 prompt，呼叫 Ollama /api/chat。

防幻覺約束都在 system prompt：只准根據 context 回答、沒把握就明說。
qwen 系列會吐 <think> 推理段——同時用 /no_think 指示與事後剝除雙保險。
transport（post）可注入：測試不打網路，F8 換 OpenAI 時另做 generator 同介面。
"""

import re
from collections.abc import Callable

import requests

from rag.vector_store import Hit

# Prompt 配方（實測 qwen3:8b，過程見 DEVLOG 2026/07/10 F4）：
# ①不用 system role——只要 system prompt 提到拒答句，think-off 的 qwen3:8b 就無條件拒答
# ②指令放 context 之後（recency）、拒答條件放最後一句
# ③think 必須關——開了反而對「部分相關」鑽牛角尖拒答
_INSTRUCTIONS = (
    "請用繁體中文回答上面的問題：先給結論，再列依據並標注【資料 N】編號，"
    "只能引用資料中出現的數字，不得自行推算或編造。"
    "若上面所有資料經檢視後都與問題完全無關，才回覆「目前資料庫沒有相關優惠資訊」。"
)
_THINK_TAG = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
# 冷載入 8B 模型實測約 24 秒 + 生成時間；PRD 的 30 秒逾時是 API 層（F5）的契約，
# transport 層放寬到 120 秒讓冷啟動活得下來
_TIMEOUT = 120.0

PostFn = Callable[[str, dict], dict]


def _http_post(url: str, payload: dict) -> dict:
    response = requests.post(url, json=payload, timeout=_TIMEOUT)
    response.raise_for_status()
    return response.json()


class OllamaGenerator:
    def __init__(self, base_url: str, model: str, post: PostFn = _http_post) -> None:
        self._url = f"{base_url.rstrip('/')}/api/chat"
        self._model = model
        self._post = post

    def generate(self, question: str, hits: list[Hit]) -> str:
        context = "\n\n".join(
            f"【資料 {i + 1}】{hit.text}\n（效期至：{hit.metadata.get('valid_to') or '未標示'}）"
            for i, hit in enumerate(hits)
        )
        payload = {
            "model": self._model,
            "stream": False,
            # qwen3 硬關 thinking（實測軟開關 /no_think 無效；關掉後 12s → <1s）
            "think": False,
            # 12 chunks × ~450 字的 context 會爆 Ollama 預設 4096，明確給足
            "options": {"num_ctx": 8192},
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"以下是優惠資料庫的檢索結果：\n\n{context}\n\n"
                        f"問題：{question}\n\n{_INSTRUCTIONS}"
                    ),
                },
            ],
        }
        reply = self._post(self._url, payload)["message"]["content"]
        return _THINK_TAG.sub("", reply).strip()
