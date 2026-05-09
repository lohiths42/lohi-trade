"""Unit tests for the offline-mode registry guard (Task 19.1).

Exercises :func:`src.research.providers.registry.get_llm` and
:func:`src.research.providers.registry.get_embeddings` with
``LOHI_RESEARCH_OFFLINE`` set / unset. The guard MUST refuse every
cloud LLM / embeddings provider at the registry edge with a
structured :class:`CloudProviderForbiddenError` naming the offending
provider and role (Req 9.4, design §14).

Key invariants pinned here:

* Offline mode forbids every cloud LLM provider named in
  ``_CLOUD_LLM_PROVIDERS`` (``nvidia_nim`` / ``openai`` /
  ``anthropic`` / ``gemini`` / ``groq`` / ``together`` /
  ``openrouter``).
* Offline mode forbids every cloud embeddings provider named in
  ``_CLOUD_EMBEDDINGS_PROVIDERS`` (``nvidia_nim`` / ``openai``).
* Offline mode allows ``ollama`` for LLMs and
  ``sentence_transformers`` / ``ollama`` for embeddings — the guard
  does not raise :class:`CloudProviderForbiddenError` for these,
  even if the underlying adapter fails for a different reason
  (missing dep, missing model, etc.).
* Online (env unset) the guard never fires; any raised error is
  *not* :class:`CloudProviderForbiddenError`.

The tests avoid standing up real adapters — cloud providers raise
before factory resolution (by design, Req 9.4), and non-cloud
providers are allowed to raise whatever they like as long as it is
not :class:`CloudProviderForbiddenError`.
"""

from __future__ import annotations

import pytest

from src.research.providers.errors import CloudProviderForbiddenError
from src.research.providers.registry import get_embeddings, get_llm


# --------------------------------------------------------------------------- #
# LLM role — online                                                           #
# --------------------------------------------------------------------------- #


def test_cloud_llm_allowed_when_online(monkeypatch: pytest.MonkeyPatch) -> None:
    """Online mode never raises :class:`CloudProviderForbiddenError`.

    When ``LOHI_RESEARCH_OFFLINE`` is unset, the registry MUST proceed
    to the factory lookup for every provider. A cloud provider may
    still fail for other reasons (missing API key, missing optional
    dependency) — but the failure shape must not be
    :class:`CloudProviderForbiddenError`.
    """
    monkeypatch.delenv("LOHI_RESEARCH_OFFLINE", raising=False)

    try:
        get_llm({"provider": "nvidia_nim", "model": "meta/llama-3.1-70b-instruct"})
    except CloudProviderForbiddenError:
        pytest.fail(
            "CloudProviderForbiddenError must not fire when offline mode is off."
        )
    except Exception:
        # Any other error is acceptable — the adapter may still fail
        # for auth / dependency reasons. We only care that the
        # offline guard didn't fire.
        pass


# --------------------------------------------------------------------------- #
# LLM role — offline                                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "provider",
    [
        "nvidia_nim",
        "openai",
        "anthropic",
        "gemini",
        "groq",
        "together",
        "openrouter",
    ],
)
def test_cloud_llm_forbidden_when_offline(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    """Offline mode refuses every cloud LLM provider (Req 9.4, design §14).

    Parametrised across the full :data:`_CLOUD_LLM_PROVIDERS` set so
    the test ensures drift between the code and this list fails
    loudly in CI.
    """
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "true")

    with pytest.raises(CloudProviderForbiddenError) as excinfo:
        get_llm({"provider": provider, "model": "any"})

    assert excinfo.value.provider == provider
    assert excinfo.value.role == "llm"
    # Message format is part of the contract (design §14 log grep).
    assert "LOHI_RESEARCH_OFFLINE=true" in str(excinfo.value)
    assert f"'{provider}'" in str(excinfo.value) or repr(provider) in str(
        excinfo.value
    )


def test_cloud_llm_forbidden_with_env_value_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``LOHI_RESEARCH_OFFLINE`` accepts ``true`` / ``1`` / ``yes`` (any case).

    Mirrors the ``_is_offline`` helper contract documented in
    ``registry.py`` and the ``research.offline_mode`` YAML
    interpolation in ``config/settings.yaml``.
    """
    for value in ("true", "True", "TRUE", "1", "yes", "Yes"):
        monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", value)
        with pytest.raises(CloudProviderForbiddenError):
            get_llm({"provider": "openai"})


def test_ollama_llm_allowed_when_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ollama is the non-cloud LLM path — the guard must stay silent (Req 7.5).

    The adapter itself may still raise (e.g. ``httpx`` missing, model
    not pulled). We only care that the offline guard does not fire.
    """
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "true")

    try:
        get_llm({"provider": "ollama", "model": "llama3"})
    except CloudProviderForbiddenError:
        pytest.fail(
            "ollama is a non-cloud LLM provider; the offline guard must not fire."
        )
    except Exception:
        # Any other adapter-level failure is fine for this test.
        pass


# --------------------------------------------------------------------------- #
# Embeddings role — online                                                    #
# --------------------------------------------------------------------------- #


def test_cloud_embeddings_allowed_when_online(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Online mode never raises :class:`CloudProviderForbiddenError`."""
    monkeypatch.delenv("LOHI_RESEARCH_OFFLINE", raising=False)

    try:
        get_embeddings({"provider": "openai", "model": "text-embedding-3-small"})
    except CloudProviderForbiddenError:
        pytest.fail(
            "CloudProviderForbiddenError must not fire when offline mode is off."
        )
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Embeddings role — offline                                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("provider", ["nvidia_nim", "openai"])
def test_cloud_embeddings_forbidden_when_offline(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    """Offline mode refuses every cloud embeddings provider (Req 9.4)."""
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "true")

    with pytest.raises(CloudProviderForbiddenError) as excinfo:
        get_embeddings({"provider": provider, "model": "any"})

    assert excinfo.value.provider == provider
    assert excinfo.value.role == "embeddings"
    assert "LOHI_RESEARCH_OFFLINE=true" in str(excinfo.value)


def test_sentence_transformers_embeddings_allowed_when_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sentence_transformers`` is the project default local embeddings backend.

    The offline guard must not fire for it (design §3.1, Req 2.5).
    """
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "true")

    try:
        get_embeddings(
            {
                "provider": "sentence_transformers",
                "model": "BAAI/bge-small-en-v1.5",
            }
        )
    except CloudProviderForbiddenError:
        pytest.fail(
            "sentence_transformers is a local embeddings provider; "
            "the offline guard must not fire."
        )
    except Exception:
        # Missing optional dependency is fine — not our concern here.
        pass


def test_ollama_embeddings_allowed_when_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ollama is a non-cloud embeddings path (design §3.1)."""
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "true")

    try:
        get_embeddings({"provider": "ollama", "model": "nomic-embed-text"})
    except CloudProviderForbiddenError:
        pytest.fail(
            "ollama is a non-cloud embeddings provider; "
            "the offline guard must not fire."
        )
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Env-value falsy cases                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", ["", "false", "0", "no", "False", "NO"])
def test_offline_disabled_for_falsy_env_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    """Any non-truthy env value leaves the guard inert — online behaviour."""
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", value)

    try:
        get_llm({"provider": "openai"})
    except CloudProviderForbiddenError:
        pytest.fail(
            f"Falsy env value {value!r} must not activate the offline guard."
        )
    except Exception:
        pass
