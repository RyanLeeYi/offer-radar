"""offer-radar API 的 HTTP client——bot 唯一的後端出口（邊界：不 import rag/、api/，
讀 config 不違反邊界）。

transport（post/get）可注入：測試不打網路。連線層失敗（API 沒起、DNS 等）
一律轉成 ApiUnavailableError，讓 handler 對使用者說人話。
"""

from collections.abc import Callable
from dataclasses import dataclass

import requests

from config.settings import QUERY_TIMEOUT_SECONDS

# API 層 /query 逾時契約見 config/settings.py；client 要等得比 server 久，
# 加安全邊際導出，不寫死第二個獨立數字（F18）
_TIMEOUT_MARGIN_SECONDS = 5.0
_QUERY_TIMEOUT = QUERY_TIMEOUT_SECONDS + _TIMEOUT_MARGIN_SECONDS
_HEALTH_TIMEOUT = 5.0


@dataclass(frozen=True)
class ApiResult:
    status: int
    body: dict


class ApiUnavailableError(Exception):
    """API 連不上（服務沒起、網路問題）——非 HTTP 錯誤碼。"""


PostFn = Callable[[str, dict, float], ApiResult]
GetFn = Callable[[str, float], ApiResult]


def _request(method: str, url: str, timeout: float, payload: dict | None = None) -> ApiResult:
    # RequestException 涵蓋連線失敗與非 JSON body（JSONDecodeError 是其子類）
    try:
        response = requests.request(method, url, json=payload, timeout=timeout)
        return ApiResult(status=response.status_code, body=response.json())
    except requests.RequestException as exc:
        raise ApiUnavailableError(str(exc)) from exc


def _http_post(url: str, payload: dict, timeout: float) -> ApiResult:
    return _request("POST", url, timeout, payload)


def _http_get(url: str, timeout: float) -> ApiResult:
    return _request("GET", url, timeout)


class OfferRadarClient:
    def __init__(self, base_url: str, post: PostFn = _http_post, get: GetFn = _http_get) -> None:
        self._base_url = base_url.rstrip("/")
        self._post = post
        self._get = get

    def query(self, question: str) -> ApiResult:
        return self._post(f"{self._base_url}/query", {"question": question}, _QUERY_TIMEOUT)

    def health(self) -> ApiResult:
        return self._get(f"{self._base_url}/health", _HEALTH_TIMEOUT)
