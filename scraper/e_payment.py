"""電子支付爬蟲入口：``python -m scraper.e_payment``（PRD R2）。

行為契約同 R1（隔離、失敗非 0 exit、只 upsert），由 scraper/runner.py 保證；
兩來源：街口（jkopay）、icash Pay（icashpay），名單見 PRD R2 註記（D8）。
"""

import sys
from collections.abc import Callable

from scraper.runner import Source, cli_main
from scraper.sources import icashpay, jkopay


def build_sources(get: Callable[[str], str]) -> list[Source]:
    return [
        Source(name="jkopay", fetch=lambda: jkopay.fetch(get)),
        Source(name="icashpay", fetch=lambda: icashpay.fetch(get)),
    ]


def main() -> int:
    return cli_main(build_sources)


if __name__ == "__main__":
    sys.exit(main())
