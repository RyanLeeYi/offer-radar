"""從問題抽關鍵詞候選：滑動 n-gram（2–4 字）+ 停用字過濾，不依賴斷詞器。

商家名多為 2–4 個中文字（全家、蝦皮、好市多、便利商店）。斷詞器對新商家名
會切錯，n-gram 窮舉 + $contains 精確匹配反而穩：不在語料裡的雜訊 gram
（「市多刷」）自然匹配不到任何文件，無害。
"""

import re

# 疑問詞、量詞、動詞等組成的 gram 不會是商家名；gram 內全是這些字就跳過
_STOP_CHARS = set("的了嗎哪些什麼怎麼有沒是要去刷卡張最比較划算優惠推薦請問一個哪能可以用付款嘛呢啊")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+]{2,}")  # momo、Uber、7-11 的英數字商家名
_NON_CJK = re.compile(r"[^一-鿿]")

MIN_LEN = 2
MAX_LEN = 4


def candidate_terms(question: str) -> list[str]:
    """抽關鍵詞候選：英數字詞整個保留、中文滑動 n-gram（去重、保序、長詞優先）。"""
    seen: dict[str, None] = {}
    for word in _LATIN_WORD.findall(question):
        seen.setdefault(word, None)
    for segment in _NON_CJK.sub(" ", question).split():
        for length in range(MAX_LEN, MIN_LEN - 1, -1):
            for start in range(len(segment) - length + 1):
                gram = segment[start : start + length]
                if all(ch in _STOP_CHARS for ch in gram):
                    continue
                seen.setdefault(gram, None)
    return list(seen)
