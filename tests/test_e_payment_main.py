"""電子支付爬蟲入口（F7）：來源接線測試。

失敗隔離／exit code／transaction 行為由共用 runner 保證（test_credit_card_main.py），
這裡只驗 e_payment 接對了兩個來源。
"""

from scraper.e_payment import build_sources


def test_build_sources_wires_jkopay_and_icashpay():
    sources = build_sources(lambda url: "")
    assert [s.name for s in sources] == ["jkopay", "icashpay"]
    assert all(callable(s.fetch) for s in sources)
