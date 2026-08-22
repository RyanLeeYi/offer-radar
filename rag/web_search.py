"""Tavily 搜尋：把組好的搜尋詞打進 Tavily API，取回搜尋結果。

只負責「打 API + 解析回應」。搜尋詞怎麼組（品牌層優先、退類別、都沒有就不搜）與
結果怎麼變成結構化 Offer，交給 ``rag/extractor.py``——網搜內容本身視為不可信輸入，
獨立於這一層（設計見 docs/superpowers/specs/2026-07-12-web-search-fallback-design.md）。
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from config.settings import Settings

_ENDPOINT = "https://api.tavily.com/search"
_TIMEOUT = 30.0

# headers 獨立於 payload：Tavily 的認證是 Authorization: Bearer（2026-08 官方 API reference
# 查證），把金鑰塞進 body 的 api_key 是舊式整合寫法，現行端點不吃
PostFn = Callable[[str, dict, dict], dict]


@dataclass(frozen=True)
class SearchResult:
    """一筆 Tavily 搜尋結果。"""

    title: str
    url: str
    content: str


def _http_post(url: str, payload: dict, headers: dict) -> dict:
    response = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
    response.raise_for_status()
    return response.json()


class TavilySearch:
    """Tavily Search API 的薄封裝。``post`` 可注入，測試一律注入 fake，不打真網路。"""

    def __init__(self, api_key: str, post: PostFn | None = None) -> None:
        self._api_key = api_key
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._post = post or _http_post

    def search(self, query: str, include_domains: list[str] | None = None) -> list[SearchResult]:
        """打 Tavily 搜尋；``include_domains`` 優先鎖官網網域（設計文件的搜尋粒度決策）。"""
        payload: dict = {"query": query}
        if include_domains:
            payload["include_domains"] = include_domains
        response = self._post(_ENDPOINT, payload, self._headers)
        return [
            SearchResult(
                title=result.get("title", ""),
                url=result.get("url", ""),
                content=result.get("content", ""),
            )
            for result in response.get("results", [])
        ]


def build_search(settings: "Settings") -> TavilySearch:
    """缺 ``TAVILY_API_KEY`` 即 fail fast——網搜是背景 job 的一環，缺 key 不該悄悄跳過。"""
    if not settings.tavily_api_key:
        raise ValueError("TAVILY_API_KEY 未設定，請在 .env 填入後再啟動（免費額度 1000 次/月）")
    return TavilySearch(api_key=settings.tavily_api_key)
