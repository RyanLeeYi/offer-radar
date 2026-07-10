"""信用卡優惠來源：每個模組一家銀行，介面統一為

- ``fetch(get: Callable[[str], str]) -> list[Offer]``：get 由呼叫端注入（真跑用
  PoliteClient.get_text，測試用 fixture getter），來源本身不碰網路細節。
- 解析函式為純函式，版面大改解析不出必要欄位時 raise ValueError（不回空殼）。
"""
