"""向量化入庫：``python -m rag.ingest``（PRD R3）。

SQLite 未過期優惠 → 切塊 → embedding → ChromaDB 全量重建。
chunk 文字帶「銀行 + 標題」前綴強化檢索訊號；metadata 含
offer_id / valid_to / source_url / trust_tier（檢索後可溯源、可過濾過期、可標未驗證）。
已過期的 web_unverified 資料在 list_active_offers 就被擋掉，不會進 ChromaDB。
R3 驗收口徑：ChromaDB distinct offer_id 數 = SQLite 未過期優惠筆數。
"""

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from sqlite3 import Connection

from config.settings import Settings
from rag.chunker import split_text
from rag.vector_store import VectorStore
from scraper.db import init_db, list_active_offers

logger = logging.getLogger(__name__)

EmbedFn = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class IngestResult:
    offers: int
    chunks: int


def ingest(conn: Connection, store: VectorStore, embed: EmbedFn, today: date) -> IngestResult:
    """全量重建：讀未過期優惠 → 切塊 → embedding → 寫入 ChromaDB。重跑 idempotent。"""
    active = list_active_offers(conn, today)

    ids: list[str] = []
    texts: list[str] = []
    metadatas: list[dict] = []
    for offer_id, offer in active:
        source = offer.bank or offer.provider or ""
        for index, piece in enumerate(split_text(offer.content)):
            ids.append(f"{offer_id}:{index}")
            texts.append(f"{source}｜{offer.title}\n{piece}")
            metadatas.append(
                {
                    "offer_id": offer_id,
                    "title": offer.title,
                    # Chroma metadata 不收 None：無期限以空字串表示
                    "valid_to": offer.valid_to.isoformat() if offer.valid_to else "",
                    "source_url": offer.source_url,
                    # 檢索端據此標示未驗證來源（F12 分層信任的落地點）
                    "trust_tier": offer.trust_tier,
                }
            )

    store.rebuild()
    if ids:
        store.upsert(ids=ids, texts=texts, embeddings=embed(texts), metadatas=metadatas)
    # rebuild 會清掉 collection metadata，stats 要在重建後補回（/health 的資料來源）
    store.set_ingest_stats(
        when=datetime.now().astimezone().isoformat(timespec="seconds"), offers=len(active)
    )
    logger.info("ingest 完成：%d 筆優惠 → %d chunks", len(active), len(ids))
    return IngestResult(offers=len(active), chunks=len(ids))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings()
    from rag.embedder import Embedder  # 延後 import：載 torch 很慢，測試不需要

    conn = init_db(settings.database_path)
    try:
        store = VectorStore(path=settings.chroma_path)
        embedder = Embedder(settings.embedding_model)
        result = ingest(conn, store, embedder.embed_passages, date.today())
    finally:
        conn.close()
    print(f"offers={result.offers} chunks={result.chunks}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
