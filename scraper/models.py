"""優惠資料模型。

欄位對應 PRD「介面契約 — SQLite offers 表」；驗證在模型邊界 fail fast。
"""

from dataclasses import dataclass
from datetime import date, datetime

SOURCE_TYPES = frozenset({"credit_card", "e_payment"})

_REQUIRED_TEXT_FIELDS = ("title", "content", "source_url")


@dataclass(frozen=True)
class Offer:
    """單筆優惠。frozen：一律建新物件，不原地修改。"""

    source_type: str
    bank: str | None
    provider: str | None
    title: str
    content: str
    channel: str | None
    reward_rate: str | None
    valid_from: date | None
    valid_to: date | None
    source_url: str
    scraped_at: datetime

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(
                f"source_type 必須是 {sorted(SOURCE_TYPES)} 之一，收到：{self.source_type!r}"
            )
        for field_name in _REQUIRED_TEXT_FIELDS:
            value = getattr(self, field_name)
            if not value or not value.strip():
                raise ValueError(f"{field_name} 不得為空")
        if self.source_type == "credit_card" and not self.bank:
            raise ValueError("credit_card 優惠必須有 bank（PRD R1）")
        if self.source_type == "e_payment" and not self.provider:
            raise ValueError("e_payment 優惠必須有 provider（PRD R2）")
