"""F13: Tavily 搜尋薄封裝測試。post 全程注入 fake，不打真網路。"""

import pytest

from config.settings import Settings
from rag.web_search import TavilySearch, build_search


class TestTavilySearch:
    def test_search_parses_results(self):
        calls: list[dict] = []

        def fake_post(url: str, payload: dict, headers: dict) -> dict:
            calls.append({"url": url, "payload": payload, "headers": headers})
            return {
                "results": [
                    {"title": "全聯信用卡優惠", "url": "https://a.example.com", "content": "內容 A"},
                    {"title": "全聯行動支付回饋", "url": "https://b.example.com", "content": "內容 B"},
                ]
            }

        search = TavilySearch(api_key="tvly-test", post=fake_post)
        results = search.search("全聯 信用卡優惠")

        assert [r.title for r in results] == ["全聯信用卡優惠", "全聯行動支付回饋"]
        assert [r.url for r in results] == ["https://a.example.com", "https://b.example.com"]
        assert [r.content for r in results] == ["內容 A", "內容 B"]
        assert calls[0]["url"] == "https://api.tavily.com/search"
        # 認證走 Authorization header，不是 body 的 api_key（現行 Tavily API）
        assert calls[0]["headers"]["Authorization"] == "Bearer tvly-test"
        assert "api_key" not in calls[0]["payload"]
        assert calls[0]["payload"]["query"] == "全聯 信用卡優惠"
        assert "include_domains" not in calls[0]["payload"]

    def test_search_passes_include_domains(self):
        calls: list[dict] = []

        def fake_post(url: str, payload: dict, headers: dict) -> dict:
            calls.append(payload)
            return {"results": []}

        search = TavilySearch(api_key="tvly-test", post=fake_post)
        search.search("全聯 信用卡優惠", include_domains=["pxpay.com.tw"])

        assert calls[0]["include_domains"] == ["pxpay.com.tw"]

    def test_search_empty_results(self):
        search = TavilySearch(api_key="tvly-test", post=lambda url, payload, headers: {"results": []})
        assert search.search("查無此物") == []


class TestBuildSearch:
    def test_missing_key_fails_fast(self):
        settings = Settings(_env_file=None, tavily_api_key="")
        with pytest.raises(ValueError):
            build_search(settings)

    def test_builds_with_key(self):
        settings = Settings(_env_file=None, tavily_api_key="tvly-test")
        search = build_search(settings)
        assert isinstance(search, TavilySearch)
        assert search._api_key == "tvly-test"
