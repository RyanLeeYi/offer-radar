"""信用卡爬蟲入口：``python -m scraper.credit_card``（PRD R1）。

行為契約（隔離、失敗非 0 exit、只 upsert）由 scraper/runner.py 保證；
三來源：國泰、台新、富邦（名單見 PRD R1 註記，D4）。
"""

import sys
from collections.abc import Callable

from scraper.runner import Source, cli_main
from scraper.sources import cathay, fubon, taishin


def build_sources(get: Callable[[str], str]) -> list[Source]:
    return [
        Source(name="cathay", fetch=lambda: cathay.fetch(get)),
        Source(name="taishin", fetch=lambda: taishin.fetch(get)),
        Source(name="fubon", fetch=lambda: fubon.fetch(get)),
    ]


def main() -> int:
    return cli_main(build_sources)


if __name__ == "__main__":
    sys.exit(main())
