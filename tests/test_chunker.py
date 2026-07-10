"""chunker 測試：段落優先切塊、上限內合併、超長段落硬切。"""

from rag.chunker import split_text


class TestSplitText:
    def test_short_text_single_chunk(self):
        assert split_text("國泰卡好市多 3% 回饋", max_chars=450) == ["國泰卡好市多 3% 回饋"]

    def test_paragraphs_merged_up_to_limit(self):
        text = "第一段。\n\n第二段。\n\n第三段。"
        chunks = split_text(text, max_chars=450)
        assert chunks == ["第一段。\n第二段。\n第三段。"]

    def test_long_text_splits_at_paragraph_boundary(self):
        para_a = "甲" * 300
        para_b = "乙" * 300
        chunks = split_text(f"{para_a}\n\n{para_b}", max_chars=450)
        assert chunks == [para_a, para_b]  # 塞不進同一塊 → 段落邊界切

    def test_oversized_paragraph_hard_split(self):
        text = "丙" * 1000
        chunks = split_text(text, max_chars=450)
        assert all(len(c) <= 450 for c in chunks)
        assert "".join(chunks) == text  # 硬切不掉字

    def test_no_empty_chunks(self):
        chunks = split_text("\n\n只有一段\n\n\n\n", max_chars=450)
        assert chunks == ["只有一段"]

    def test_empty_text_returns_empty_list(self):
        assert split_text("   \n\n  ", max_chars=450) == []
