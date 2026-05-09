"""FastAPI gateway entry point with Socket.IO mount.

Wires all backend services, middleware, and push notification triggers.
Requirements: 29.5, 12.6
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# ─── Repo-root sys.path insertion ──────────────────────────────────────────
# The gateway process runs with ``backend-gateway/`` as its working
# directory, so its own ``app.*`` imports resolve. Research code lives
# one level up under ``src/research/*`` and is imported by both the
# research router and the shared error-envelope middleware. Prepending
# the repo root here makes ``from src.research...`` resolve without
# requiring every operator to ``pip install -e .`` the parent project.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
import socketio

from app.config import CORS_ORIGINS
from app.middleware.caching import CacheHeadersMiddleware
from app.middleware.errors import register_research_exception_handlers
from app.middleware.jwt_auth import JWTAuthMiddleware
from app.middleware.security import InputSanitizationMiddleware, RequestLoggingMiddleware
from app.routers import auth, auth_v2, health, positions, orders, trades, bias, signals, analytics, config, kill_switch, logs, paper_trading, broker, trade_notes, verification, bank, stock_universe, watchlist, screener, broker_v2, market_data, chatbot, users, admin, public_stocks
from app.routers import research as research_router
from app.routers import setup as setup_router
from app.routers import market as market_router
from app.services.feature_gate import initialize_registry
from app.websocket import consume_research_streams, register_events
from app.services.redis_consumer import consume_streams
from app.services.push_notification_service import PushNotificationService
from app.services.db_service import (
    ensure_trade_notes_table,
    create_pg_pool,
    get_pg_pool,
    close_pg_pool,
    create_redis_pool,
    create_async_redis_pool,
    close_redis_pools,
)
from app.services.stock_universe_service import StockUniverseService
from app.services.sector_service import SectorService
from app.services.screener_service import ScreenerEngine
from app.services.live_data_service import LiveDataService
from app.routers.stock_universe import set_stock_universe_services
from app.routers.screener import set_screener_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(title="Lohi-TRADE Gateway", version="1.0.0")

# ── Middleware stack (outermost → innermost) ─────────────────────────────────
# Starlette runs add_middleware in reverse order, so the *last* added is
# outermost.  We want: Logging → CORS → JWTAuth → GZip → Caching → Sanitization → route handler.

app.add_middleware(InputSanitizationMiddleware)
app.add_middleware(CacheHeadersMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(JWTAuthMiddleware)  # Sets request.state.user_id + app.state.current_user_id for RLS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)

# Include REST routers
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(auth_v2.router, prefix="/api/v2", tags=["auth-v2"])
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(positions.router, prefix="/api", tags=["positions"])
app.include_router(orders.router, prefix="/api", tags=["orders"])
app.include_router(trades.router, prefix="/api", tags=["trades"])
app.include_router(bias.router, prefix="/api", tags=["bias"])
app.include_router(signals.router, prefix="/api", tags=["signals"])
app.include_router(analytics.router, prefix="/api", tags=["analytics"])
app.include_router(config.router, prefix="/api", tags=["config"])
app.include_router(kill_switch.router, prefix="/api", tags=["kill-switch"])
app.include_router(logs.router, prefix="/api", tags=["logs"])
app.include_router(paper_trading.router, prefix="/api", tags=["paper-trading"])
app.include_router(broker.router, prefix="/api", tags=["broker"])
app.include_router(trade_notes.router, prefix="/api", tags=["trade-notes"])
app.include_router(verification.router, prefix="/api/v2", tags=["verification"])
app.include_router(bank.router, prefix="/api/v2", tags=["bank-fund"])
app.include_router(stock_universe.router, prefix="/api/v2", tags=["stock-universe"])
app.include_router(watchlist.router, prefix="/api/v2", tags=["watchlists"])
app.include_router(screener.router, prefix="/api/v2", tags=["screener"])
app.include_router(broker_v2.router, prefix="/api/v2", tags=["broker-v2"])
app.include_router(market_data.router, prefix="/api/v2", tags=["market-data"])
app.include_router(chatbot.router, prefix="/api/v2", tags=["chatbot"])
app.include_router(users.router, prefix="/api/v2", tags=["users"])
app.include_router(admin.router, prefix="/api/v2", tags=["admin"])
app.include_router(public_stocks.router, prefix="/api/v2/public", tags=["public-stocks"])
app.include_router(setup_router.router, prefix="/api", tags=["setup"])
app.include_router(market_router.router, prefix="/api", tags=["market"])

# ── Lohi-Research gateway surface (Task 1.6) ─────────────────────────────────
# Conditionally mount the Lohi-Research router at /api/v2/research when
# ``research.enabled`` is true in config/settings.yaml (default true). Reading
# the flag here avoids a hard dependency on the research package before the
# rest of Phase 1–20 lands. Requirements: 7.7, 8.2 | Design: §3.12, §5.1.

def _research_enabled() -> bool:
    """Return True if ``settings.research.enabled`` is truthy (default True)."""
    import yaml
    from app.config import CONFIG_PATH
    try:
        with open(CONFIG_PATH, "r") as f:
            settings = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("settings.yaml not found at %s; defaulting research.enabled=true", CONFIG_PATH)
        return True
    except Exception:
        logger.exception("Failed to parse settings.yaml; defaulting research.enabled=true")
        return True
    research_cfg = settings.get("research") or {}
    return bool(research_cfg.get("enabled", True))


if _research_enabled():
    app.include_router(research_router.router, prefix="/api/v2/research", tags=["research"])
    # Install the structured-error envelope handlers (Task 16.4) so
    # provider / config / latency-budget exceptions surface with the
    # canonical {"error": {...}} shape even when an endpoint handler
    # forgets its own try/except (design §5.3).
    register_research_exception_handlers(app)
    logger.info("Lohi-Research router mounted at /api/v2/research")
else:
    logger.info("Lohi-Research router disabled via settings.research.enabled=false")

# ── Push notification service (FCM) ─────────────────────────────────────────
push_service = PushNotificationService()
app.state.push_service = push_service

# Socket.IO server
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=CORS_ORIGINS)
register_events(sio)

# ASGI app combining FastAPI + Socket.IO
socket_app = socketio.ASGIApp(sio, app)


def _build_orchestrator(llm_provider, emb_provider, vs_provider):
    """Build a minimal ResearchOrchestrator for the gateway.

    This factory is called lazily on each ``POST /runs`` request.
    It constructs the orchestrator with the providers wired at startup.
    """
    from src.research.agents.orchestrator import ResearchOrchestrator
    from src.research.agents.filings import FilingsAgent
    from src.research.agents.fundamentals import FundamentalsAgent
    from src.research.agents.news_sentiment import NewsSentimentAgent
    from src.research.agents.technicals import TechnicalsAgent
    from src.research.agents.peer_sector import PeerSectorAgent
    from src.research.agents.macro import MacroAgent
    from src.research.agents.synthesizer import Synthesizer
    from src.research.index.retriever import HybridRetriever

    # Build retriever (hybrid BM25 + dense)
    retriever = HybridRetriever(
        embeddings=emb_provider,
        vector_store=vs_provider,
        bm25_weight=0.4,
        dense_weight=0.6,
        top_k=40,
    )

    # Build sub-agents (they receive the LLM; retriever is passed
    # at invocation time by the orchestrator, not at construction)
    sub_agents = [
        FilingsAgent(llm=llm_provider),
        FundamentalsAgent(llm=llm_provider),
        NewsSentimentAgent(llm=llm_provider),
        TechnicalsAgent(llm=llm_provider),
        PeerSectorAgent(llm=llm_provider),
        MacroAgent(llm=llm_provider),
    ]

    synthesizer = Synthesizer(llm=llm_provider)

    # Wrap the rule-based judge to match the JudgeFn interface expected
    # by the orchestrator's resynthesis loop (brief=..., retry_count=...)
    from uuid import uuid4 as _uuid4

    async def _judge_fn(*, brief, retry_count=0, **kwargs):
        from src.research.judge.rule_based import invoke_rule_based
        return await invoke_rule_based(
            run_id=_uuid4(),
            brief=brief,
            chunks=[],  # no chunks in vector store yet
            retry_count=retry_count,
        )

    return ResearchOrchestrator(
        sub_agents=sub_agents,
        synthesizer=synthesizer,
        judge_fn=_judge_fn,
        retriever=retriever,
        chat_llm=llm_provider,
        concurrency_cap=6,
        min_score=0.7,
        max_retries=1,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup + shutdown orchestration (FastAPI ≥ 0.93 lifespan API).

    Replaces the deprecated ``@app.on_event('startup' | 'shutdown')``
    pair. Behaviour is identical: initialise pools, wire services,
    kick off the Redis consumers, then reverse on shutdown.
    """
    # ── Startup ──────────────────────────────────────────────────────
    # Initialize the service registry / feature gate (Requirements 4.1–4.5)
    logger.info("Initializing service registry and feature gates...")
    initialize_registry()

    logger.info("Ensuring trade_notes table exists...")
    ensure_trade_notes_table()

    # Initialize connection pools (Requirement 34.6)
    logger.info("Creating asyncpg connection pool (min=5, max=20)...")
    pool = await create_pg_pool()

    logger.info("Creating Redis connection pools (max=10)...")
    create_redis_pool()
    create_async_redis_pool()

    # Wire up stock universe, sector, and screener services
    if pool is not None:
        logger.info("Wiring stock universe, sector, and screener services...")
        stock_svc = StockUniverseService(db_pool=pool)
        sector_svc = SectorService(db_pool=pool)
        screener_engine = ScreenerEngine(db_pool=pool)
        set_stock_universe_services(stock_svc, sector_svc)
        set_screener_service(screener_engine, db_pool=pool)
        logger.info("Stock/screener services initialized")

        # Start live data service (auto-seeds if DB is empty, refreshes periodically)
        live_data_svc = LiveDataService(db_pool=pool)
        app.state.live_data_service = live_data_svc
        await live_data_svc.start()
        logger.info("LiveDataService started — will auto-seed and refresh stock data")
    else:
        logger.warning(
            "PostgreSQL pool not available — falling back to in-memory stock universe. "
            "This is fine for UI demos but will NOT persist data. "
            "Start docker-compose up -d postgres for the full experience."
        )
        from app.services.stock_universe_fallback import (
            FallbackStockUniverseService,
            FallbackSectorService,
        )
        fallback_stock = FallbackStockUniverseService()
        fallback_sector = FallbackSectorService()
        set_stock_universe_services(fallback_stock, fallback_sector)  # type: ignore[arg-type]

        # Also initialize a pool-less WatchlistService so the UI gets empty
        # arrays instead of 503 when browsing watchlists.
        try:
            from app.services.watchlist_service import WatchlistService
            from app.routers.watchlist import set_watchlist_service
            set_watchlist_service(WatchlistService(db_pool=None))
        except Exception:
            logger.exception("Failed to init fallback WatchlistService")

    # Schedule the Redis consumer + Research bridge as background tasks.
    # `asyncio.create_task` is the modern equivalent of
    # `asyncio.get_event_loop().create_task(...)` and is safe inside a
    # running coroutine on Python 3.10–3.14.
    logger.info("Starting Redis stream consumer...")
    consumer_task = asyncio.create_task(_start_consumer())
    research_bridge_task: asyncio.Task | None = None
    if _research_enabled():
        research_bridge_task = asyncio.create_task(_start_research_bridge())

    # ── Wire ResearchService with real providers ─────────────────────
    if _research_enabled():
        try:
            from app.routers.research import set_research_service
            from app.services.research_service import ResearchService
            from app.services.db_service import get_pg_pool as _get_pg_pool, get_async_redis_client as _get_async_redis

            # Lazy-import provider registry so the gateway still starts
            # even if research deps are partially missing.
            from src.research.providers.registry import (
                get_llm,
                get_embeddings,
                get_vector_store,
            )

            import yaml as _yaml
            from app.config import CONFIG_PATH as _cfg_path

            _settings = {}
            try:
                with open(_cfg_path, "r") as _f:
                    _settings = _yaml.safe_load(_f) or {}
            except Exception:
                pass
            _research_cfg = _settings.get("research", {})
            _providers_cfg = _research_cfg.get("providers", {})
            _vs_cfg = _research_cfg.get("vector_store", {})

            # Detect offline mode — override providers to local-only
            import os as _os
            _offline = _os.environ.get("LOHI_RESEARCH_OFFLINE", "").strip().lower() in ("true", "1", "yes")
            if _offline:
                logger.info("Research offline mode active — using Ollama + sentence-transformers")
                _chat_cfg = {"provider": "ollama", "model": _os.environ.get("LOHI_RESEARCH_OLLAMA_MODEL", "llama3.1:8b")}
                _emb_cfg = {"provider": "sentence_transformers", "model": "BAAI/bge-small-en-v1.5"}
            else:
                _chat_cfg = _providers_cfg.get("chat", {})
                _emb_cfg = _providers_cfg.get("embeddings", {})

            _llm_provider = None
            _emb_provider = None
            _vs_provider = None

            try:
                _llm_provider = get_llm(_chat_cfg)
                logger.info("Research LLM provider: %s", type(_llm_provider).__name__)
            except Exception as e:
                logger.warning("Research LLM provider init failed: %s", e)

            try:
                _emb_provider = get_embeddings(_emb_cfg)
                logger.info("Research embeddings provider: %s", type(_emb_provider).__name__)
            except Exception as e:
                logger.warning("Research embeddings provider init failed: %s", e)

            try:
                # In offline mode, force chroma to avoid async probe issues
                if _offline:
                    import pathlib as _pathlib
                    _chroma_path = str(_pathlib.Path(_REPO_ROOT) / "data" / "research" / "chroma")
                    _vs_cfg_resolved = {"backend": "chroma", "chroma": {"path": _chroma_path}}
                else:
                    _vs_cfg_resolved = _vs_cfg
                _vs_provider = get_vector_store(_vs_cfg_resolved)
                logger.info("Research vector store: %s", type(_vs_provider).__name__)
            except Exception as e:
                logger.warning("Research vector store init failed: %s", e)

            _async_redis = None
            try:
                _async_redis = _get_async_redis()
            except Exception:
                pass

            svc = ResearchService(
                db_pool=pool,
                redis=_async_redis,
                vector_store=_vs_provider,
                embeddings_provider=_emb_provider,
                llm_provider=_llm_provider,
                orchestrator_factory=lambda: _build_orchestrator(
                    _llm_provider, _emb_provider, _vs_provider
                ),
            )
            set_research_service(svc)
            logger.info("ResearchService wired with providers + orchestrator")
        except Exception:
            logger.exception("Failed to wire ResearchService — research endpoints will return 'pending'")

    logger.info("Lohi-TRADE Gateway started")

    # Hand control to FastAPI — the server now serves requests. Code
    # after `yield` runs on shutdown.
    try:
        yield
    finally:
        # ── Shutdown ────────────────────────────────────────────────
        logger.info("Shutting down connection pools...")
        # Stop the background tasks cleanly so Redis connections drain
        # before the pools close.
        for task in (consumer_task, research_bridge_task):
            if task is None or task.done():
                continue
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                # Swallow — cancellation and late-stage connection
                # errors are expected during shutdown.
                pass
        # Stop live data service
        live_svc = getattr(app.state, "live_data_service", None)
        if live_svc:
            await live_svc.stop()
        await close_pg_pool()
        await close_redis_pools()
        logger.info("Lohi-TRADE Gateway stopped")


async def _start_consumer():
    """Run the Redis consumer in a thread to avoid blocking the event loop."""
    try:
        await consume_streams(sio)
    except Exception as e:
        logger.error(f"Redis consumer failed: {e}")


async def _start_research_bridge():
    """Run the Lohi-Research Redis → Socket.IO bridge (Task 16.3).

    Forwards ``research:partials`` stream entries and research
    pubsub channels to ``research:<run_id>`` Socket.IO rooms
    (design §5.2). Connection errors inside the bridge are logged;
    a crashed bridge must not crash the whole gateway process.
    """
    try:
        await consume_research_streams(sio)
    except Exception as e:
        logger.error(f"Lohi-Research Socket.IO bridge failed: {e}")


# ── Wire the lifespan context manager into the FastAPI app ──────────────────
# `lifespan` is defined further up but references background-task helpers
# (`_start_consumer`, `_start_research_bridge`) that are only fully
# defined by this point. FastAPI looks up the context manager at server
# start, so assigning it here is safe and keeps the module's top-down
# read flow intact.
app.router.lifespan_context = lifespan
