"""CLI 問答：``python -m rag.query "去好市多刷哪張卡最划算"``（F4 驗收入口）。"""

import argparse
import sys

from config.settings import Settings
from rag.pipeline import build_default


def main() -> int:
    parser = argparse.ArgumentParser(description="優惠問答（RAG）")
    parser.add_argument("question", help="要問的問題，例：去好市多刷哪張卡最划算")
    args = parser.parse_args()

    result = build_default(Settings()).pipeline.answer(args.question)
    print(result.answer)
    if result.sources:
        print("\n來源：")
        for source in result.sources:
            valid = f"（效期至 {source.valid_to}）" if source.valid_to else ""
            print(f"- {source.title}{valid}\n  {source.source_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
