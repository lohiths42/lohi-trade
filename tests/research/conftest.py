"""Pytest conftest skeleton for the Lohi-Research backend test suite.

This file will eventually host fixtures that swap in the in-memory fake
providers (``FakeLLMProvider``, ``FakeEmbeddingsProvider``,
``FakeVectorStore``) defined in Task 2.19 of the lohi-research-dashboard
spec (design §17.2).

For now it is intentionally a no-op so that pytest can collect the
``tests/research/`` package without import errors before the fakes module
exists. Do NOT import from the (not-yet-created) fakes module here; add
the imports and activate the fixtures as part of Task 2.19.
"""

import pytest  # noqa: F401  (kept so placeholder fixture decorators below remain valid once uncommented)


# TODO(Task 2.19): Enable ``fake_llm`` fixture once
# ``tests.research.fakes.FakeLLMProvider`` exists.
#
# @pytest.fixture
# def fake_llm():
#     from tests.research.fakes import FakeLLMProvider
#     return FakeLLMProvider()


# TODO(Task 2.19): Enable ``fake_embeddings`` fixture once
# ``tests.research.fakes.FakeEmbeddingsProvider`` exists.
#
# @pytest.fixture
# def fake_embeddings():
#     from tests.research.fakes import FakeEmbeddingsProvider
#     return FakeEmbeddingsProvider()


# TODO(Task 2.19): Enable ``fake_vector_store`` fixture once
# ``tests.research.fakes.FakeVectorStore`` exists.
#
# @pytest.fixture
# def fake_vector_store():
#     from tests.research.fakes import FakeVectorStore
#     return FakeVectorStore()
