"""通用 LLM completion 測試（rag/llm.py，F24 補齊）：provider 選擇與 claude subprocess
全用假件，不打真服務／CLI。

原本 build_completion／_ollama_complete／_openai_complete 完全沒有測試（只被
rag/extractor.py 間接使用，未被任何測試呼叫過）；F24 新增 claude 分支時一併補上
provider 選擇的回歸覆蓋，避免只測 generator 側漏了 completion 側的線。
"""

from types import SimpleNamespace

from rag.llm import build_completion


class TestBuildCompletion:
    def _settings(self, **overrides):
        from config.settings import Settings

        base = {"llm_provider": "ollama", "openai_api_key": "", "openai_model": "gpt-4o-mini"}
        return Settings(**{**base, **overrides})

    def test_ollama_provider_builds_callable(self):
        assert callable(build_completion(self._settings()))

    def test_openai_provider_with_key_builds_callable(self):
        assert callable(
            build_completion(self._settings(llm_provider="openai", openai_api_key="sk-test"))
        )

    def test_openai_provider_without_key_fails_fast(self):
        try:
            build_completion(self._settings(llm_provider="openai", openai_api_key=""))
        except ValueError as error:
            assert "OPENAI_API_KEY" in str(error)
        else:
            raise AssertionError("缺 OPENAI_API_KEY 時應在建構期即 raise，不得延到查詢時")

    def test_claude_provider_builds_callable(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: r"C:\fake\claude.exe")
        assert callable(build_completion(self._settings(llm_provider="claude")))

    def test_claude_provider_missing_cli_fails_fast(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)
        try:
            build_completion(self._settings(llm_provider="claude"))
        except ValueError as error:
            assert "claude" in str(error)
        else:
            raise AssertionError("claude CLI 缺失時應在建構期即 fail fast，不得延到查詢時")

    def test_unknown_provider_fails_fast(self):
        try:
            build_completion(self._settings(llm_provider="gemini"))
        except ValueError as error:
            assert "gemini" in str(error)
        else:
            raise AssertionError("未知 provider 應 fail fast")


class TestClaudeComplete:
    """rag/llm.py 的 _claude_complete：組單一 prompt 呼叫 claude CLI，剝除 <think> 段。"""

    def test_normal_reply_and_think_strip(self):
        from rag.llm import _claude_complete

        calls: list[list[str]] = []

        def fake_run(args: list[str]):
            calls.append(args)
            return SimpleNamespace(
                returncode=0, stdout="<think>使用者想比較卡片…</think>國泰卡 3% 回饋最划算", stderr=""
            )

        complete = _claude_complete(run=fake_run)
        answer = complete("去好市多刷哪張卡")
        assert answer == "國泰卡 3% 回饋最划算"
        assert calls[0][:2] == ["claude", "-p"]
        assert "去好市多刷哪張卡" in calls[0][2]

    def test_cli_nonzero_exit_fails_fast_with_readable_error(self):
        """未登入等 CLI 執行失敗場景：非零結束碼即 raise，帶 stderr 供除錯。"""
        from rag.llm import _claude_complete

        def fake_run(args: list[str]):
            return SimpleNamespace(
                returncode=1, stdout="", stderr="Invalid API key · Please run /login"
            )

        complete = _claude_complete(run=fake_run)
        try:
            complete("q")
        except RuntimeError as error:
            assert "login" in str(error)
        else:
            raise AssertionError("claude CLI 非零結束碼時應 fail fast")
