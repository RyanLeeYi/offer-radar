"""切塊：段落優先、上限內合併、超長段落硬切。

優惠文案多在數百字內（一塊搞定）；上限設計對齊 multilingual embedding 模型
的有效序列長度，切太碎反而稀釋語意。
"""

DEFAULT_MAX_CHARS = 450


def split_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """把全文切成 ≤ max_chars 的塊：先按段落合併裝箱，裝不下的段落硬切。"""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        for piece in _hard_split(paragraph, max_chars):
            candidate = f"{current}\n{piece}" if current else piece
            if len(candidate) <= max_chars:
                current = candidate
            else:
                chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


def _hard_split(paragraph: str, max_chars: int) -> list[str]:
    """單一段落就超過上限時直接按長度切（不掉字）。"""
    if len(paragraph) <= max_chars:
        return [paragraph]
    return [paragraph[i : i + max_chars] for i in range(0, len(paragraph), max_chars)]
