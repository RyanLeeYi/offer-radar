"""禮貌 HTTP client 測試：UA 自報身分、請求間隔 ≥ 1 秒（CLAUDE.md 規則 6）。"""

from scraper.http import USER_AGENT, PoliteClient


class FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.encoding = "utf-8"

    def raise_for_status(self) -> None:
        pass


class FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(f"body of {url}")


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(min_interval: float = 1.0) -> tuple[PoliteClient, FakeSession, FakeClock]:
    session = FakeSession()
    clock = FakeClock()
    client = PoliteClient(
        session=session, min_interval=min_interval, clock=clock.monotonic, sleep=clock.sleep
    )
    return client, session, clock


def test_user_agent_identifies_project():
    assert "offer-radar" in USER_AGENT
    _, session, _ = make_client()
    assert session.headers["User-Agent"] == USER_AGENT


def test_first_request_does_not_sleep():
    client, _, clock = make_client()
    client.get_text("https://example.com/1")
    assert clock.sleeps == []


def test_consecutive_requests_wait_min_interval():
    client, _, clock = make_client(min_interval=1.0)
    client.get_text("https://example.com/1")
    client.get_text("https://example.com/2")
    assert len(clock.sleeps) == 1
    assert clock.sleeps[0] >= 0.99


def test_get_text_returns_body():
    client, _, _ = make_client()
    assert client.get_text("https://example.com/x") == "body of https://example.com/x"
