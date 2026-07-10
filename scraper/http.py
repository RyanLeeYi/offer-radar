"""禮貌 HTTP client：自報身分 UA、請求間隔 ≥ 1 秒、非 200 直接炸（CLAUDE.md 規則 6）。"""

import time
from collections.abc import Callable

import requests

USER_AGENT = "Mozilla/5.0 (compatible; offer-radar/0.1; personal side project)"
DEFAULT_TIMEOUT = 20.0
MIN_INTERVAL_SECONDS = 1.0


class PoliteClient:
    """帶最小請求間隔的 GET client。clock / sleep 可注入以便測試。"""

    def __init__(
        self,
        session: requests.Session | None = None,
        min_interval: float = MIN_INTERVAL_SECONDS,
        timeout: float = DEFAULT_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session = session if session is not None else requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._min_interval = min_interval
        self._timeout = timeout
        self._clock = clock
        self._sleep = sleep
        self._last_request_at: float | None = None

    def get_text(self, url: str) -> str:
        """GET 一個 URL 回傳 body 文字；距上次請求不足 min_interval 先睡滿。"""
        if self._last_request_at is not None:
            elapsed = self._clock() - self._last_request_at
            if elapsed < self._min_interval:
                self._sleep(self._min_interval - elapsed)
        response = self._session.get(url, timeout=self._timeout)
        self._last_request_at = self._clock()
        response.raise_for_status()
        # 三個目標站都是 UTF-8；header 沒標 charset 時 requests 會猜 ISO-8859-1，強制修正
        if response.encoding is None or response.encoding.lower() == "iso-8859-1":
            response.encoding = "utf-8"
        return response.text
