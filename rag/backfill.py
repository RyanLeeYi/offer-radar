"""查無背景補查 job（F15）：miss_log → 查詢正規化 → 網搜 → 抽取 → 入庫 → ingest。

`python -m rag.backfill` 手動或排程執行。**非同步、不推播**：補到的資料要等使用者
下次再問才搜得到（設計見 docs/superpowers/specs/2026-07-12-web-search-fallback-design.md）。

單筆 miss 失敗只 log 不中斷整批；整個 job 是獨立 process，壞掉也影響不到前台查詢。
"""

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from sqlite3 import Connection

from config.settings import Settings
from rag.extractor import Entity, build_search_terms, extract_offers, normalize_query
from rag.llm import LlmFn
from rag.miss_log import DEDUPE_WINDOW, init_miss_log, list_misses, set_entity
from rag.web_search import SearchResult
from scraper.db import init_db, upsert_offer
from scraper.models import Offer

logger = logging.getLogger(__name__)

# ponytail: 單次執行處理的 miss 筆數上限。注意這**不等於** Tavily 請求數——每個 entity
# 最多 2 組搜尋詞 × 2 次（鎖官網 + 放寬）= 4 次請求，最壞情況是 limit × 4。免費額度
# 1000 次/月，照預設值算約 12 輪滿載。要精準控管就改成對 requests 計數設上限。
DEFAULT_LIMIT = 20

# 正規化抽不出品牌也抽不出類別時填進 entity 的標記：這種 miss 重試幾次結果都一樣，
# 留 null 會永遠佔住 pending 名額，把後來的 miss 餓死（每輪還白燒 limit 次 LLM 呼叫）。
UNRESOLVED = "?"

# include_domains 可帶也可不帶：第二個參數有預設值，TavilySearch.search 直接相容
SearchFn = Callable[..., list[SearchResult]]


@dataclass(frozen=True)
class BackfillResult:
    processed: int  # 這輪消化掉的 miss 筆數
    searched: int  # 實際發出搜尋的 entity 數（看 24h 去重擋掉多少）
    requests: int  # 實際打出去的 Tavily 請求數（額度消耗看這個，不是 searched）
    stored: int  # 通過 schema 驗證、寫進 offers 的筆數


def backfill(
    conn: Connection,
    complete: LlmFn,
    search: SearchFn,
    now: datetime,
    limit: int = DEFAULT_LIMIT,
) -> BackfillResult:
    """消化尚未正規化的 miss。回傳這輪的處理量，供呼叫端決定要不要重跑 ingest。

    去重兩層：①同一輪內同 entity 只搜一次 ②24h 內已經有同 entity 的 miss 記錄就跳過
    （miss 記下來之後很快就會被這個 job 消化，所以 created_at 足以當「搜過了」的近似）。
    """
    init_miss_log(conn)
    misses = list_misses(conn)
    recent = {
        m.entity
        for m in misses
        if m.entity and m.entity != UNRESOLVED and now - m.created_at < DEDUPE_WINDOW
    }
    pending = [m for m in misses if m.entity is None][:limit]

    seen: set[str] = set()
    searched = requests = stored = 0
    for miss in pending:
        entity = _normalize(miss.query, complete)
        key = entity.brand or entity.category
        if key is None:
            # 連類別都抽不出就不搜（設計文件的防線）。標成 UNRESOLVED 而非留 null：
            # 同一句話重試幾次結果都一樣，留著只會排擠後面的 miss
            logger.info("抽不出品牌與類別，不搜：%r", miss.query)
            set_entity(conn, miss.id, UNRESOLVED)
            continue
        set_entity(conn, miss.id, key)
        if key in seen or key in recent:
            logger.info("24h 內已搜過 %r，跳過：%r", key, miss.query)
            continue
        seen.add(key)
        searched += 1
        offers, calls = _search_and_extract(entity, complete, search, now)
        requests += calls
        for offer in offers:
            upsert_offer(conn, offer)
            stored += 1
        conn.commit()
    logger.info(
        "補查完成：processed=%d searched=%d requests=%d stored=%d",
        len(pending), searched, requests, stored,
    )
    return BackfillResult(
        processed=len(pending), searched=searched, requests=requests, stored=stored
    )


def _normalize(question: str, complete: LlmFn) -> Entity:
    """正規化失敗視同抽不出（回全 None）——補查是旁路，不該讓單筆炸掉整輪。"""
    try:
        return normalize_query(question, complete)
    except Exception:
        logger.exception("查詢正規化失敗，當作抽不出處理：%r", question)
        return Entity(brand=None, product=None, category=None)


def _search_and_extract(
    entity: Entity, complete: LlmFn, search: SearchFn, now: datetime
) -> tuple[list[Offer], int]:
    """先鎖官網網域搜一次，搜不到才放寬到全網。回傳 (抽到的 offers, 實際請求數)。

    官網網域是 LLM 推測的，猜錯只會得到空結果——沒有退路的話整個品牌就白搜了。
    """
    results: list[SearchResult] = []
    requests = 0
    for term in build_search_terms(entity):
        try:
            hits, calls = _search_term(term, entity.official_domain, search)
        except Exception:
            logger.exception("搜尋失敗，跳過這組搜尋詞：%r", term)
            requests += 1
            continue
        requests += calls
        results.extend(hits)
    if not results:
        return [], requests
    return extract_offers(results, complete, now), requests


def _search_term(
    term: str, domain: str | None, search: SearchFn
) -> tuple[list[SearchResult], int]:
    if domain:
        restricted = search(term, include_domains=[domain])
        if restricted:
            return restricted, 1
        return search(term), 2
    return search(term), 1


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings()
    from rag.embedder import Embedder  # 延後 import：載 torch 很慢
    from rag.ingest import ingest
    from rag.llm import build_completion
    from rag.vector_store import VectorStore
    from rag.web_search import build_search

    complete = build_completion(settings)
    searcher = build_search(settings)  # 缺 TAVILY_API_KEY 在這裡 fail fast
    conn = init_db(settings.database_path)
    try:
        result = backfill(conn, complete, searcher.search, datetime.now())
        logger.info("Tavily 請求數 %d（免費額度 1000 次/月）", result.requests)
        if result.stored:
            # 有新資料才重建向量庫——ingest 是全量重建，沒新增就是白跑幾十分鐘
            store = VectorStore(path=settings.chroma_path)
            ingest(conn, store, Embedder(settings.embedding_model).embed_passages, date.today())
    finally:
        conn.close()
    print(
        f"processed={result.processed} searched={result.searched} "
        f"requests={result.requests} stored={result.stored}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
