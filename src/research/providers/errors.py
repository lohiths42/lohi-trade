"""Provider-related exceptions (design §3.1, §5.3).

This module defines the structured exception types every concrete provider
adapter raises so the gateway can translate them into the existing
structured error envelope (`{"error": {"code", "provider", "model",
"message"}}`) without silent fallback (Req 2.10, Req 8.8).

The design only names `ProviderAuthError(provider, model, error_code)`
explicitly (§3.1, §5.3), so that is the one concrete class defined here.
A small `ProviderError` base is included purely so downstream code can
`except ProviderError` as a catch-all without depending on a specific
subclass; it introduces no new requirement and is not referenced by the
design. Additional provider exceptions (timeout, rate-limit, etc.) will
be added alongside the adapters that need them in later tasks.

`UnknownProviderError` is raised by ``registry.py`` (Task 2.2) when a
config block names a provider that is not present in the corresponding
factory registry. It exists here so `from .errors import *` keeps every
provider-layer exception co-located (Req 2.12, design §9).

`CloudProviderForbiddenError` is raised by ``registry.py`` when
``LOHI_RESEARCH_OFFLINE=true`` and the configured LLM or embeddings
provider is a cloud backend (Req 9.4, design §14). It is co-located
here for the same "single provider-errors module" reason.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for all provider adapter exceptions.

    Not defined verbatim in the design document. It exists so that call
    sites which want a catch-all can write `except ProviderError` without
    coupling to a specific subclass. All subclasses SHALL carry enough
    structured data for the gateway to populate the error envelope in
    design §5.3.
    """


class ProviderAuthError(ProviderError):
    """Raised when a provider rejects the configured credentials.

    Maps directly to the structured error envelope in design §5.3:

        {"error": {"code": "PROVIDER_AUTH_FAILED",
                    "provider": ..., "model": ..., "message": ...}}

    Satisfies Req 2.10 — Lohi_Research fails closed with a structured
    error carrying `provider`, `model`, and `error_code`, and never falls
    back silently to a different provider.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        error_code: str,
        message: str | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.error_code = error_code
        # Human-readable tail; the structured envelope is assembled by
        # the gateway from the three fields above.
        self.message = (
            message
            if message is not None
            else f"Provider authentication failed: {provider}/{model} ({error_code})"
        )
        super().__init__(self.message)

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return (
            f"ProviderAuthError(provider={self.provider!r}, "
            f"model={self.model!r}, error_code={self.error_code!r})"
        )


class UnknownProviderError(ProviderError):
    """Raised when a config block names a provider with no registered factory.

    The ``registry.py`` builders (``get_llm``, ``get_embeddings``,
    ``get_vector_store``) raise this whenever ``cfg["provider"]`` — or
    ``cfg["backend"]`` for vector stores — does not match any key in the
    corresponding factory registry (Req 2.12, design §9).

    Carries:

    - ``kind``       : ``"llm" | "embeddings" | "vector_store"`` — which
                        registry was consulted.
    - ``name``       : the unknown provider/backend name from config.
    - ``registered`` : sorted tuple of names that *are* registered; echoed
                        back to operators so a typo is self-diagnosing
                        from the exception message alone.
    """

    def __init__(
        self,
        kind: str,
        name: str,
        registered: tuple[str, ...],
    ) -> None:
        self.kind = kind
        self.name = name
        self.registered = registered
        known = ", ".join(registered) if registered else "<none registered>"
        super().__init__(
            f"Unknown {kind} provider {name!r}; registered: {known}.",
        )


class CloudProviderForbiddenError(ProviderError):
    """Raised when offline mode refuses to instantiate a cloud provider.

    Satisfies Req 9.4 and design §14 ("offline enforcement"): when
    ``LOHI_RESEARCH_OFFLINE=true`` the registry MUST refuse to build any
    cloud LLM or cloud embeddings adapter and fail fast with a structured
    error naming the offending provider and role. Non-cloud providers
    (``ollama`` for LLMs; ``sentence_transformers`` and ``ollama`` for
    embeddings) continue to build normally.

    Carries:

    - ``provider`` : the offending provider name from config
                     (``cfg["provider"]``).
    - ``role``     : ``"llm" | "embeddings"`` — which registry role
                     rejected the provider.

    The message is pinned to a single canonical phrase so operators
    grepping logs for offline-mode enforcement hits always find the
    same string regardless of which role triggered it.
    """

    def __init__(self, provider: str, role: str) -> None:
        self.provider = provider
        self.role = role
        super().__init__(
            f"Cloud provider {provider!r} is forbidden when "
            f"LOHI_RESEARCH_OFFLINE=true (role={role}).",
        )


__all__ = [
    "CloudProviderForbiddenError",
    "ProviderAuthError",
    "ProviderError",
    "UnknownProviderError",
]
