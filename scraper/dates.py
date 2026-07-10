"""活動期間文字解析：從優惠頁原文抽 (valid_from, valid_to)。

只處理明確的日期區間（如 2026/07/08 ~ 2026/07/14、2026/7/1-9/30）；
解析不了一律回 (None, None)——PRD 允許 valid_to 為 null，猜錯比不猜糟。
"""

import re
from datetime import date

# 起日（含年）→ 分隔符（~ - ～ 至，中間允許時間字樣）→ 迄日（年可省略，省略時沿用起日年份）
_PERIOD = re.compile(
    r"(\d{4})[/.](\d{1,2})[/.](\d{1,2})"
    r"[^~\-～至]{0,15}[~\-～至]\s*"
    r"(?:(\d{4})[/.])?(\d{1,2})[/.](\d{1,2})"
)


def parse_period(text: str) -> tuple[date | None, date | None]:
    """從文字抽出第一組日期區間；抽不出或日期非法回 (None, None)。"""
    match = _PERIOD.search(text)
    if not match:
        return (None, None)
    start_year, start_month, start_day, end_year, end_month, end_day = match.groups()
    try:
        start = date(int(start_year), int(start_month), int(start_day))
        end = date(int(end_year or start_year), int(end_month), int(end_day))
        if end < start and end_year is None:
            # 跨年簡寫（2026/12/15-1/15）：迄日沒寫年且早於起日 → 進位一年
            end = date(start.year + 1, int(end_month), int(end_day))
    except ValueError:
        return (None, None)
    if end < start:
        return (None, None)  # 兩邊都有年卻迄早於起：資料有問題，不猜
    return (start, end)
