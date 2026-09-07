# offer-radar

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?style=flat-square)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square)](https://fastapi.tiangolo.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-vector%20store-ff6f00?style=flat-square)](https://www.trychroma.com)
[![Tests](https://img.shields.io/badge/tests-322%20passing-brightgreen?style=flat-square)](#testing)
[![Coverage](https://img.shields.io/badge/coverage-89%25-brightgreen?style=flat-square)](#testing)

[繁體中文](README.zh-TW.md)

**Ask "which card should I use at Costco?" in plain language and get an answer grounded in real Taiwanese credit-card and e-payment offers, with sources.**

Card and wallet promotions in Taiwan are scattered across bank sites and change every other week. offer-radar crawls them into a vector store and answers questions through a Retrieval-Augmented Generation (RAG) pipeline that only uses what is actually in the database. Every conclusion cites its source, and when nothing matches it says so instead of inventing an offer.

> [!NOTE]
> This is a portfolio project. The goal was to build a RAG pipeline end to end (scrape, chunk, embed, retrieve, generate) with a multilingual embedding model, an anti-hallucination prompt, a local LLM, and provider switching, and to keep it honest with 300+ tests.

## Features

- **Hybrid retrieval**: Chinese n-gram exact match plus vector similarity. Pure vector search kept burying "Costco" inside long terms-and-conditions chunks; exact keyword hits now bypass the distance threshold.
- **Grounded answers**: the prompt refuses when no retrieved offer is relevant, and the pipeline clears the source list on refusal so the API never returns citations for a non-answer.
- **Trust tiers**: official sources are `verified`; offers extracted from PTT threads or web search are `web_unverified` and get a warning label in the answer. Expired unverified data never reaches the vector store.
- **Self-healing scrapers**: when a site changes layout and parsing fails, the raw page is kept as evidence and an LLM extractor produces a fallback record tagged `llm_fallback`, so ingestion degrades instead of silently dropping a source.
- **Miss log**: unanswerable queries are recorded with a timestamp so a background job can backfill data later.
- **Three interfaces, one pipeline**: CLI, FastAPI (with Swagger), and a Telegram bot that only talks HTTP.
- **Local by default**: Ollama `qwen3:8b` and `BAAI/bge-m3` run on your machine. Switch to OpenAI with one environment variable.

## Architecture

```
  Bank / wallet sites                                    User
  Credit cards: Cathay, Taishin, Fubon                     |
  E-payments: JKOPAY, icash Pay, iPASS MONEY           Telegram
  Community: PTT Lifeismoney                               |
     |                                                     v
     v  scraper/  (requests + BeautifulSoup)            bot/  (HTTP only)
  SQLite  data/offers.db   <-- upsert only, sources isolated
     |                                                     |
     v  rag.ingest                                         v
  chunk -> embed (bge-m3) -> ChromaDB  data/chroma      api/  (FastAPI)
     |                                                     |
     +--------------->  rag/pipeline  <--------------------+
        hybrid retrieval (n-gram exact + vector)
        -> anti-hallucination prompt -> LLM (Ollama default, OpenAI optional)
```

Layer boundaries are strict and tested (see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)): `scraper/` never imports `rag/`; ChromaDB is only touched through `rag/vector_store.py`; `api/` only calls `rag/pipeline.py`; `bot/` only speaks HTTP.

| Layer | Technology |
|---|---|
| Scraping | requests + BeautifulSoup (static HTML, AEM `.model.json`, Next.js RSC payloads) |
| Raw storage | SQLite |
| Vector store | ChromaDB |
| Embedding | sentence-transformers, `BAAI/bge-m3` (multilingual, local) |
| Retrieval | hybrid: Chinese n-gram `$contains` + cosine similarity |
| LLM | Ollama `qwen3:8b` (default) or OpenAI |
| API | FastAPI |
| Interface | Telegram bot |
| Tooling | uv, pytest, ruff |

## Getting started

**Prerequisites**: [uv](https://docs.astral.sh/uv/), Python 3.11+, [Ollama](https://ollama.com/) (skip if you use OpenAI).

```bash
# 1. Dependencies, .env from template, smoke test
./init.sh

# 2. Local model (skip for OpenAI)
ollama pull qwen3:8b

# 3. Crawl offers into SQLite (polite: custom UA, >= 1 s between requests)
uv run python -m scraper.credit_card     # Cathay, Taishin, Fubon
uv run python -m scraper.e_payment       # JKOPAY, icash Pay
uv run python -m rag.ipass_ingest        # iPASS MONEY news (LLM extraction)
uv run python -m rag.ptt_ingest          # PTT Lifeismoney (LLM extraction, web_unverified)

# 4. Chunk, embed, and load ChromaDB (first run downloads bge-m3)
uv run python -m rag.ingest

# 5. Ask
uv run python -m rag.query "去好市多刷哪張卡最划算"
```

## Usage

**CLI**

```bash
uv run python -m rag.query "便利商店有什麼行動支付優惠"
```

**HTTP API**

```bash
uv run uvicorn api.main:app            # Swagger UI at http://localhost:8000/docs
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "去好市多刷哪張卡最划算"}'
# GET /health -> {ok, offers_count, last_ingest_at}
```

**Telegram bot** (set `TELEGRAM_BOT_TOKEN` in `.env`)

One-shot launcher for Ollama, API, and bot on Windows: double-click `run.bat` or run `./run.ps1`. Stop with `Ctrl+C` or `stop.bat`. Or start each process yourself:

```bash
ollama serve
uv run uvicorn api.main:app
uv run python -m bot.main              # long polling
```

**Example behaviour**

| Question | What happens |
|---|---|
| 去好市多刷哪張卡最划算 | Retrieves matching offers, compares them, cites each as【資料 N】 |
| 便利商店有什麼行動支付優惠 | Aggregates convenience-store promotions across wallets |
| 去火星旅遊要刷哪張卡 | No relevant data: replies that the database has nothing, with no sources |

## Configuration

All settings live in `.env` (template: [`.env.example`](.env.example)). The ones you are most likely to change:

```bash
LLM_PROVIDER=ollama            # or openai
OLLAMA_MODEL=qwen3:8b          # prompt recipe is tuned for this model
OPENAI_API_KEY=                # required when LLM_PROVIDER=openai; startup fails fast if missing
EMBEDDING_MODEL=BAAI/bge-m3
TELEGRAM_BOT_TOKEN=
TAVILY_API_KEY=                # optional: enables `rag.backfill` web search for missed queries
```

> [!TIP]
> Use `127.0.0.1` rather than `localhost` for local service URLs on Windows. `localhost` resolves to IPv6 first and each request waits about two seconds before falling back to IPv4.

## Testing

```bash
uv run pytest                  # 322 tests
uv run pytest --cov=.          # ~89% coverage
uv run ruff check .
```

Scraper parsers are tested against local HTML fixtures. No test hits a live site.

## Design notes

- **Vector search alone has a ceiling for exact merchant names.** Three embedding models in a row failed to rank the Costco clause into the top-k, so retrieval became hybrid: keyword hits are exempt from the distance threshold.
- **Two lines of defence against hallucination.** The retrieval threshold is a sanity check; the real guard is the prompt instruction to refuse when every hit is irrelevant, plus the pipeline clearing `sources`. `qwen3:8b` turned out to be sensitive to prompt position (a refusal rule in the system role made it refuse everything), so the recipe was found experimentally.
- **Long-running API vs. batch ingest.** A full rebuild of the ChromaDB collection changes its UUID, so the API never caches the collection handle and calls `get_or_create` per request.
- **Validate at the data boundary.** The `Offer` model enforces required fields and the `source_type` contract in `__post_init__`, so bad records fail at scrape time rather than at query time.
- **Fail loudly, not silently.** A source that raises or returns zero rows logs an error and sets a non-zero exit code, while other sources still commit in their own transactions.

## Limitations

- Data is refreshed by running the scrapers manually. There is no scheduler and no live crawl at query time.
- Sources: three card issuers, three e-payment providers, one community board. LINE Pay (offers live inside an in-app SPA) and E.SUN (WAF blocks non-browser clients) would need a headless browser.
- Recurring monthly campaigns are captured for the current window only.
- No web frontend, no user accounts, no exact cashback arithmetic. The LLM explains and compares; it does not guarantee sums.
