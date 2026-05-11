"""Unit tests for ChatbotService — Gen AI chatbot with RAG over user trading data.

Tests cover: LLMClient, ChatbotService (chat, history, session management),
RAG retrieval, conversation persistence, message building, serialization,
and numeric accuracy validation.

Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7, 19.5
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.chatbot_service import (
    REDIS_CHAT_KEY_PREFIX,
    REDIS_CHAT_TTL_SECONDS,
    MAX_CONVERSATION_EXCHANGES,
    NO_DATA_RESPONSE,
    SYSTEM_PROMPT,
    ChatbotService,
    ChatResponse,
    ChartGenerator,
    LLMClient,
    Message,
    MessageRole,
    RAGContext,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_llm_client(api_key="test-key", model="gpt-4o-mini") -> LLMClient:
    return LLMClient(api_key=api_key, model=model)


def _make_mock_pool():
    """Create a mock asyncpg pool with async context manager for acquire()."""
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool, conn


def _make_mock_redis():
    """Create a mock async Redis client."""
    redis = AsyncMock()
    return redis


def _make_service(
    llm_client=None, db_pool=None, redis=None, chart_gen=None
) -> ChatbotService:
    llm = llm_client or LLMClient(api_key="test-key")
    return ChatbotService(
        llm_client=llm, db_pool=db_pool, redis=redis, chart_gen=chart_gen
    )


def _make_trade_row(
    id="trade-1", symbol="RELIANCE", strategy="mean_reversion",
    entry_price=2500.0, exit_price=2550.0, quantity=10,
    realized_pnl=500.0, entry_time="2024-01-15T10:00:00",
    exit_time="2024-01-15T14:00:00",
):
    row = MagicMock()
    data = {
        "id": id, "symbol": symbol, "strategy": strategy,
        "entry_price": entry_price, "exit_price": exit_price,
        "quantity": quantity, "realized_pnl": realized_pnl,
        "entry_time": entry_time, "exit_time": exit_time,
    }
    row.__getitem__ = lambda self, key: data[key]
    row.get = lambda key, default=None: data.get(key, default)
    row.keys = lambda: data.keys()
    row.values = lambda: data.values()
    row.items = lambda: data.items()
    # Make dict(row) work
    row.__iter__ = lambda self: iter(data)
    row.__len__ = lambda self: len(data)
    return row


def _make_sentiment_row(
    ticker="RELIANCE", sentiment="BULLISH", score=0.85,
    headline="Reliance Q3 results beat estimates", created_at="2024-01-15T09:00:00",
):
    row = MagicMock()
    data = {
        "ticker": ticker, "sentiment": sentiment, "score": score,
        "headline": headline, "created_at": created_at,
    }
    row.__getitem__ = lambda self, key: data[key]
    row.get = lambda key, default=None: data.get(key, default)
    row.keys = lambda: data.keys()
    row.values = lambda: data.values()
    row.items = lambda: data.items()
    row.__iter__ = lambda self: iter(data)
    row.__len__ = lambda self: len(data)
    return row


def _make_signal_row(
    symbol="RELIANCE", signal_type="BUY", strategy="mean_reversion",
    indicator_values='{"rsi": 30}', bias_state="BULLISH",
    created_at="2024-01-15T09:30:00",
):
    row = MagicMock()
    data = {
        "symbol": symbol, "signal_type": signal_type, "strategy": strategy,
        "indicator_values": indicator_values, "bias_state": bias_state,
        "created_at": created_at,
    }
    row.__getitem__ = lambda self, key: data[key]
    row.get = lambda key, default=None: data.get(key, default)
    row.keys = lambda: data.keys()
    row.values = lambda: data.values()
    row.items = lambda: data.items()
    row.__iter__ = lambda self: iter(data)
    row.__len__ = lambda self: len(data)
    return row


# ── Message tests ────────────────────────────────────────────────────────────


class TestMessage:
    def test_to_dict(self):
        msg = Message(role=MessageRole.USER, content="hello")
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "hello"
        assert "timestamp" in d

    def test_to_dict_preserves_timestamp(self):
        msg = Message(role=MessageRole.ASSISTANT, content="hi", timestamp="2024-01-01T00:00:00")
        d = msg.to_dict()
        assert d["timestamp"] == "2024-01-01T00:00:00"

    def test_from_dict(self):
        d = {"role": "assistant", "content": "response", "timestamp": "2024-01-01T00:00:00"}
        msg = Message.from_dict(d)
        assert msg.role == MessageRole.ASSISTANT
        assert msg.content == "response"

    def test_from_dict_invalid_role_defaults_to_user(self):
        d = {"role": "unknown", "content": "test"}
        msg = Message.from_dict(d)
        assert msg.role == MessageRole.USER

    def test_from_dict_missing_content(self):
        d = {"role": "user"}
        msg = Message.from_dict(d)
        assert msg.content == ""

    def test_round_trip(self):
        original = Message(role=MessageRole.SYSTEM, content="system prompt", timestamp="2024-01-01T00:00:00")
        d = original.to_dict()
        restored = Message.from_dict(d)
        assert restored.role == original.role
        assert restored.content == original.content
        assert restored.timestamp == original.timestamp


# ── RAGContext tests ─────────────────────────────────────────────────────────


class TestRAGContext:
    def test_empty_context_has_no_data(self):
        ctx = RAGContext()
        assert not ctx.has_data

    def test_context_with_trades_has_data(self):
        ctx = RAGContext(trades=[{"id": "t1"}])
        assert ctx.has_data

    def test_context_with_sentiment_has_data(self):
        ctx = RAGContext(sentiment_logs=[{"ticker": "RELIANCE"}])
        assert ctx.has_data

    def test_context_with_signals_has_data(self):
        ctx = RAGContext(signals=[{"symbol": "RELIANCE"}])
        assert ctx.has_data

    def test_to_context_string_empty(self):
        ctx = RAGContext()
        assert ctx.to_context_string() == "No relevant data found."

    def test_to_context_string_with_trades(self):
        ctx = RAGContext(trades=[{"id": "t1", "symbol": "RELIANCE"}])
        result = ctx.to_context_string()
        assert "Recent trades" in result
        assert "RELIANCE" in result

    def test_to_context_string_with_summary(self):
        ctx = RAGContext(summary="User has 10 trades")
        result = ctx.to_context_string()
        assert "User has 10 trades" in result

    def test_to_context_string_limits_to_10_items(self):
        ctx = RAGContext(trades=[{"id": f"t{i}"} for i in range(20)])
        result = ctx.to_context_string()
        # Should only show 10 trades in the context string
        lines = [l for l in result.split("\n") if l.strip().startswith("-")]
        assert len(lines) == 10


# ── LLMClient tests ──────────────────────────────────────────────────────────


class TestLLMClient:
    def test_init_defaults(self):
        client = LLMClient()
        assert client.api_key == ""
        assert client.model == "gpt-4o-mini"
        assert "openai" in client.api_base

    def test_init_custom(self):
        client = LLMClient(api_key="key", api_base="http://localhost:8000/v1", model="llama3")
        assert client.api_key == "key"
        assert client.model == "llama3"
        assert client.api_base == "http://localhost:8000/v1"

    def test_api_base_trailing_slash_stripped(self):
        client = LLMClient(api_base="http://localhost:8000/v1/")
        assert client.api_base == "http://localhost:8000/v1"

    @pytest.mark.asyncio
    async def test_complete_no_api_key_returns_fallback(self):
        client = LLMClient(api_key="")
        messages = [Message(role=MessageRole.USER, content="hello")]
        result = await client.complete(messages)
        assert "unable to process" in result.lower() or "help" in result.lower()

    @pytest.mark.asyncio
    async def test_complete_with_api_key_calls_api(self):
        client = LLMClient(api_key="test-key")
        messages = [Message(role=MessageRole.USER, content="hello")]

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hi there!"}}]
        }

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_response
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            result = await client.complete(messages)
            assert result == "Hi there!"

    @pytest.mark.asyncio
    async def test_complete_api_error_returns_fallback(self):
        client = LLMClient(api_key="test-key")
        messages = [Message(role=MessageRole.USER, content="hello")]

        mock_http_client = AsyncMock()
        mock_http_client.post.side_effect = Exception("Connection error")
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            result = await client.complete(messages)
            assert "unable to process" in result.lower()

    def test_fallback_response_with_user_message(self):
        messages = [Message(role=MessageRole.USER, content="show my trades")]
        result = LLMClient._fallback_response(messages)
        assert "unable to process" in result.lower()

    def test_fallback_response_without_user_message(self):
        messages = [Message(role=MessageRole.SYSTEM, content="system")]
        result = LLMClient._fallback_response(messages)
        assert "help" in result.lower()


# ── ChatbotService — conversation persistence tests ──────────────────────────


class TestConversationPersistence:
    @pytest.mark.asyncio
    async def test_load_conversation_no_redis_returns_empty(self):
        svc = _make_service(redis=None)
        result = await svc._load_conversation("user-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_load_conversation_no_data_returns_empty(self):
        redis = _make_mock_redis()
        redis.get.return_value = None
        svc = _make_service(redis=redis)
        result = await svc._load_conversation("user-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_load_conversation_valid_data(self):
        redis = _make_mock_redis()
        data = [
            {"role": "user", "content": "hello", "timestamp": "2024-01-01T00:00:00"},
            {"role": "assistant", "content": "hi", "timestamp": "2024-01-01T00:00:01"},
        ]
        redis.get.return_value = json.dumps(data)
        svc = _make_service(redis=redis)
        result = await svc._load_conversation("user-1")
        assert len(result) == 2
        assert result[0].role == MessageRole.USER
        assert result[1].role == MessageRole.ASSISTANT

    @pytest.mark.asyncio
    async def test_load_conversation_invalid_json_returns_empty(self):
        redis = _make_mock_redis()
        redis.get.return_value = "not-json"
        svc = _make_service(redis=redis)
        result = await svc._load_conversation("user-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_load_conversation_redis_error_returns_empty(self):
        redis = _make_mock_redis()
        redis.get.side_effect = Exception("Redis down")
        svc = _make_service(redis=redis)
        result = await svc._load_conversation("user-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_save_conversation_no_redis_does_nothing(self):
        svc = _make_service(redis=None)
        await svc._save_conversation("user-1", [])  # Should not raise

    @pytest.mark.asyncio
    async def test_save_conversation_stores_with_ttl(self):
        redis = _make_mock_redis()
        svc = _make_service(redis=redis)
        messages = [Message(role=MessageRole.USER, content="hello")]
        await svc._save_conversation("user-1", messages)

        redis.set.assert_called_once()
        call_args = redis.set.call_args
        assert call_args[0][0] == f"{REDIS_CHAT_KEY_PREFIX}user-1"
        assert call_args[1]["ex"] == REDIS_CHAT_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_save_conversation_trims_to_max_exchanges(self):
        redis = _make_mock_redis()
        svc = _make_service(redis=redis)

        # Create more than max messages
        messages = []
        for i in range(50):
            messages.append(Message(role=MessageRole.USER, content=f"msg-{i}"))
            messages.append(Message(role=MessageRole.ASSISTANT, content=f"resp-{i}"))

        await svc._save_conversation("user-1", messages)

        call_args = redis.set.call_args
        saved_data = json.loads(call_args[0][1])
        assert len(saved_data) == MAX_CONVERSATION_EXCHANGES * 2

    @pytest.mark.asyncio
    async def test_save_conversation_redis_error_does_not_raise(self):
        redis = _make_mock_redis()
        redis.set.side_effect = Exception("Redis down")
        svc = _make_service(redis=redis)
        messages = [Message(role=MessageRole.USER, content="hello")]
        await svc._save_conversation("user-1", messages)  # Should not raise


# ── ChatbotService — RAG retrieval tests ─────────────────────────────────────


class TestRAGRetrieval:
    @pytest.mark.asyncio
    async def test_retrieve_context_no_db_pool(self):
        svc = _make_service(db_pool=None)
        ctx = await svc._retrieve_context("user-1", "show my trades")
        assert not ctx.has_data

    @pytest.mark.asyncio
    async def test_retrieve_context_fetches_user_data(self):
        pool, conn = _make_mock_pool()
        trade_rows = [_make_trade_row()]
        sentiment_rows = [_make_sentiment_row()]
        signal_rows = [_make_signal_row()]

        conn.fetch.side_effect = [trade_rows, sentiment_rows, signal_rows]

        svc = _make_service(db_pool=pool)
        ctx = await svc._retrieve_context("user-1", "show my trades")

        assert ctx.has_data
        assert len(ctx.trades) == 1
        assert len(ctx.sentiment_logs) == 1
        assert len(ctx.signals) == 1

    @pytest.mark.asyncio
    async def test_retrieve_context_uses_user_id_filter(self):
        pool, conn = _make_mock_pool()
        conn.fetch.side_effect = [[], [], []]

        svc = _make_service(db_pool=pool)
        await svc._retrieve_context("user-42", "query")

        # All three fetch calls should include user_id as parameter
        assert conn.fetch.call_count == 3
        for call in conn.fetch.call_args_list:
            args = call[0]
            assert "user_id = $1" in args[0]
            assert args[1] == "user-42"

    @pytest.mark.asyncio
    async def test_retrieve_context_db_error_returns_empty(self):
        pool, conn = _make_mock_pool()
        conn.fetch.side_effect = Exception("DB error")

        svc = _make_service(db_pool=pool)
        ctx = await svc._retrieve_context("user-1", "query")
        assert not ctx.has_data


# ── ChatbotService — message building tests ──────────────────────────────────


class TestMessageBuilding:
    def test_build_llm_messages_includes_system_prompt(self):
        svc = _make_service()
        messages = svc._build_llm_messages([], "hello", RAGContext())
        assert messages[0].role == MessageRole.SYSTEM
        assert messages[0].content == SYSTEM_PROMPT

    def test_build_llm_messages_includes_rag_context(self):
        svc = _make_service()
        ctx = RAGContext(trades=[{"id": "t1"}])
        messages = svc._build_llm_messages([], "hello", ctx)
        # System prompt + RAG context + user message
        assert len(messages) == 3
        assert "trading data context" in messages[1].content.lower()

    def test_build_llm_messages_no_rag_context_when_empty(self):
        svc = _make_service()
        messages = svc._build_llm_messages([], "hello", RAGContext())
        # System prompt + user message only
        assert len(messages) == 2

    def test_build_llm_messages_includes_history(self):
        svc = _make_service()
        history = [
            Message(role=MessageRole.USER, content="prev question"),
            Message(role=MessageRole.ASSISTANT, content="prev answer"),
        ]
        messages = svc._build_llm_messages(history, "new question", RAGContext())
        # System + 2 history + new user message
        assert len(messages) == 4
        assert messages[1].content == "prev question"
        assert messages[2].content == "prev answer"
        assert messages[3].content == "new question"

    def test_build_llm_messages_skips_system_from_history(self):
        svc = _make_service()
        history = [
            Message(role=MessageRole.SYSTEM, content="old system"),
            Message(role=MessageRole.USER, content="question"),
        ]
        messages = svc._build_llm_messages(history, "new", RAGContext())
        # System prompt + user from history + new user message
        assert len(messages) == 3
        roles = [m.role for m in messages]
        assert roles.count(MessageRole.SYSTEM) == 1


# ── ChatbotService — chat() integration tests ────────────────────────────────


class TestChat:
    @pytest.mark.asyncio
    async def test_chat_empty_user_id(self):
        svc = _make_service()
        resp = await svc.chat("", "hello")
        assert resp.text == "Please provide a message."

    @pytest.mark.asyncio
    async def test_chat_empty_message(self):
        svc = _make_service()
        resp = await svc.chat("user-1", "")
        assert resp.text == "Please provide a message."

    @pytest.mark.asyncio
    async def test_chat_whitespace_message(self):
        svc = _make_service()
        resp = await svc.chat("user-1", "   ")
        assert resp.text == "Please provide a message."

    @pytest.mark.asyncio
    async def test_chat_returns_llm_response(self):
        llm = LLMClient(api_key="test")
        llm.complete = AsyncMock(return_value="Your total P&L is ₹5000")

        redis = _make_mock_redis()
        redis.get.return_value = None

        pool, conn = _make_mock_pool()
        conn.fetch.side_effect = [
            [_make_trade_row()],  # trades
            [],  # sentiment
            [],  # signals
        ]

        svc = _make_service(llm_client=llm, db_pool=pool, redis=redis)
        resp = await svc.chat("user-1", "What is my total P&L?")

        assert resp.text == "Your total P&L is ₹5000"
        assert resp.response_time_ms >= 0
        assert "trades" in resp.sources[0]

    @pytest.mark.asyncio
    async def test_chat_no_data_returns_no_data_response(self):
        llm = LLMClient(api_key="test")
        llm.complete = AsyncMock(return_value="Some response")

        redis = _make_mock_redis()
        redis.get.return_value = None

        pool, conn = _make_mock_pool()
        conn.fetch.side_effect = [[], [], []]  # No data

        svc = _make_service(llm_client=llm, db_pool=pool, redis=redis)
        resp = await svc.chat("user-1", "Show my trades")

        assert resp.text == NO_DATA_RESPONSE

    @pytest.mark.asyncio
    async def test_chat_non_data_query_without_data_uses_llm(self):
        """Non-data queries (e.g. greetings) should use LLM even without data."""
        llm = LLMClient(api_key="test")
        llm.complete = AsyncMock(return_value="Hello! How can I help?")

        redis = _make_mock_redis()
        redis.get.return_value = None

        svc = _make_service(llm_client=llm, db_pool=None, redis=redis)
        resp = await svc.chat("user-1", "Hello there")

        assert resp.text == "Hello! How can I help?"

    @pytest.mark.asyncio
    async def test_chat_saves_conversation_to_redis(self):
        llm = LLMClient(api_key="test")
        llm.complete = AsyncMock(return_value="Response")

        redis = _make_mock_redis()
        redis.get.return_value = None

        svc = _make_service(llm_client=llm, db_pool=None, redis=redis)
        await svc.chat("user-1", "Hello")

        redis.set.assert_called_once()
        saved_data = json.loads(redis.set.call_args[0][1])
        assert len(saved_data) == 2  # user + assistant
        assert saved_data[0]["role"] == "user"
        assert saved_data[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_chat_loads_existing_conversation(self):
        llm = LLMClient(api_key="test")
        llm.complete = AsyncMock(return_value="Follow-up response")

        existing = [
            {"role": "user", "content": "first msg", "timestamp": "2024-01-01T00:00:00"},
            {"role": "assistant", "content": "first resp", "timestamp": "2024-01-01T00:00:01"},
        ]
        redis = _make_mock_redis()
        redis.get.return_value = json.dumps(existing)

        svc = _make_service(llm_client=llm, db_pool=None, redis=redis)
        await svc.chat("user-1", "Follow up")

        # LLM should receive history + new message
        call_args = llm.complete.call_args[0][0]
        user_messages = [m for m in call_args if m.role == MessageRole.USER]
        assert len(user_messages) == 2  # history + new


# ── ChatbotService — get_history and clear_session tests ─────────────────────


class TestHistoryAndSession:
    @pytest.mark.asyncio
    async def test_get_history_returns_messages(self):
        redis = _make_mock_redis()
        data = [
            {"role": "user", "content": "hello", "timestamp": "2024-01-01T00:00:00"},
            {"role": "assistant", "content": "hi", "timestamp": "2024-01-01T00:00:01"},
        ]
        redis.get.return_value = json.dumps(data)
        svc = _make_service(redis=redis)
        history = await svc.get_history("user-1")
        assert len(history) == 2
        assert history[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_get_history_empty(self):
        redis = _make_mock_redis()
        redis.get.return_value = None
        svc = _make_service(redis=redis)
        history = await svc.get_history("user-1")
        assert history == []

    @pytest.mark.asyncio
    async def test_clear_session_success(self):
        redis = _make_mock_redis()
        svc = _make_service(redis=redis)
        result = await svc.clear_session("user-1")
        assert result is True
        redis.delete.assert_called_once_with(f"{REDIS_CHAT_KEY_PREFIX}user-1")

    @pytest.mark.asyncio
    async def test_clear_session_no_redis(self):
        svc = _make_service(redis=None)
        result = await svc.clear_session("user-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_clear_session_redis_error(self):
        redis = _make_mock_redis()
        redis.delete.side_effect = Exception("Redis down")
        svc = _make_service(redis=redis)
        result = await svc.clear_session("user-1")
        assert result is False


# ── ChatbotService — helper method tests ─────────────────────────────────────


class TestHelpers:
    def test_is_data_query_english(self):
        assert ChatbotService._is_data_query("Show my trades") is True
        assert ChatbotService._is_data_query("What is my P&L?") is True
        assert ChatbotService._is_data_query("portfolio performance") is True

    def test_is_data_query_hinglish(self):
        assert ChatbotService._is_data_query("Meri kamai kitna hai?") is True
        assert ChatbotService._is_data_query("Kitna nuksan hua?") is True

    def test_is_data_query_non_data(self):
        assert ChatbotService._is_data_query("Hello") is False
        assert ChatbotService._is_data_query("What time is it?") is False

    def test_extract_sources_empty(self):
        ctx = RAGContext()
        assert ChatbotService._extract_sources(ctx) == []

    def test_extract_sources_with_data(self):
        ctx = RAGContext(
            trades=[{"id": "t1"}],
            sentiment_logs=[{"ticker": "X"}],
            signals=[{"symbol": "X"}],
        )
        sources = ChatbotService._extract_sources(ctx)
        assert len(sources) == 3
        assert "trades" in sources[0]
        assert "sentiment_logs" in sources[1]
        assert "signals" in sources[2]


# ── Serialization and validation tests ───────────────────────────────────────


class TestSerialization:
    def test_serialize_query_results(self):
        results = [{"id": "t1", "pnl": 500.0}]
        json_str = ChatbotService.serialize_query_results(results)
        parsed = json.loads(json_str)
        assert parsed[0]["id"] == "t1"
        assert parsed[0]["pnl"] == 500.0

    def test_serialize_handles_datetime(self):
        results = [{"time": datetime(2024, 1, 1, tzinfo=timezone.utc)}]
        json_str = ChatbotService.serialize_query_results(results)
        parsed = json.loads(json_str)
        assert "2024" in parsed[0]["time"]

    def test_deserialize_valid_json(self):
        result = ChatbotService.deserialize_llm_response('{"pnl": 500}')
        assert result == {"pnl": 500}

    def test_deserialize_invalid_json(self):
        result = ChatbotService.deserialize_llm_response("not json")
        assert result is None

    def test_deserialize_none_input(self):
        result = ChatbotService.deserialize_llm_response(None)
        assert result is None

    def test_validate_numeric_accuracy_within_tolerance(self):
        llm_vals = {"pnl": 500.005, "price": 2500.001}
        db_vals = {"pnl": 500.0, "price": 2500.0}
        assert ChatbotService.validate_numeric_accuracy(llm_vals, db_vals) is True

    def test_validate_numeric_accuracy_exceeds_tolerance(self):
        llm_vals = {"pnl": 501.0}
        db_vals = {"pnl": 500.0}
        assert ChatbotService.validate_numeric_accuracy(llm_vals, db_vals) is False

    def test_validate_numeric_accuracy_missing_key(self):
        llm_vals = {"pnl": 500.0, "extra": 100.0}
        db_vals = {"pnl": 500.0}
        assert ChatbotService.validate_numeric_accuracy(llm_vals, db_vals) is True

    def test_validate_numeric_accuracy_non_numeric_skipped(self):
        llm_vals = {"name": "RELIANCE", "pnl": 500.0}
        db_vals = {"name": "RELIANCE", "pnl": 500.0}
        assert ChatbotService.validate_numeric_accuracy(llm_vals, db_vals) is True


# ── ChartGenerator tests ────────────────────────────────────────────────────


class TestChartGenerator:
    def test_equity_curve_returns_svg(self):
        gen = ChartGenerator()
        result = gen.equity_curve([])
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_daily_pnl_bar_returns_svg(self):
        gen = ChartGenerator()
        result = gen.daily_pnl_bar([])
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_strategy_comparison_returns_svg(self):
        gen = ChartGenerator()
        result = gen.strategy_comparison([])
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_candlestick_returns_svg(self):
        gen = ChartGenerator()
        result = gen.candlestick([])
        assert isinstance(result, bytes)
        assert b"<svg" in result


# ── ChatResponse tests ──────────────────────────────────────────────────────


class TestChatResponse:
    def test_defaults(self):
        resp = ChatResponse(text="hello")
        assert resp.text == "hello"
        assert resp.chart_data is None
        assert resp.chart_type is None
        assert resp.sources == []
        assert resp.response_time_ms == 0

    def test_with_all_fields(self):
        resp = ChatResponse(
            text="response",
            chart_data=b"svg-data",
            chart_type="equity_curve",
            sources=["trades (5 records)"],
            response_time_ms=150,
        )
        assert resp.chart_data == b"svg-data"
        assert resp.chart_type == "equity_curve"
        assert len(resp.sources) == 1
