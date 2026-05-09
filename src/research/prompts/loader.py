"""Immutable-at-runtime prompt loader for versioned Sub_Agent templates.

Loads Markdown prompt files from ``src/research/prompts/{version}/``
and freezes each into an :class:`ImmutablePrompt` dataclass so that
runtime code cannot mutate the template text after it has been read
from disk (Req 16.6 — prompts are versioned and immutable at runtime).

The render helper performs strictly-positional substitution of
``{{KEY}}`` placeholders using the caller-supplied ``substitutions``
mapping. A missing key raises :class:`KeyError` — callers are expected
to supply every placeholder present in the template; silent empty
substitution would erase the refusal-policy block or output-schema
block, which would in turn weaken the guardrail story.

Caching
-------
Loaded templates are cached in a module-level dict keyed by
``(version, name)``. The cache is read-through and never invalidated —
template files on disk are expected to be immutable within a process
lifetime (design §3.9), so re-reading them would be wasted I/O. Tests
that need to reset the cache (e.g. when writing fixture templates on
the fly) can call :func:`_reset_cache_for_tests`.

Satisfies:
    - Req 16.6 — Sub_Agent system prompts loaded from versioned
      Prompt_Template files under ``src/research/prompts/`` and
      immutable at runtime.
    - Req 16.25 — closed-book instructions (carried in the template
      body) are preserved verbatim through the loader.

Design references:
    - §3.9 (Versioned prompt layout + shared skeleton)
    - §10.1 (Versioned prompt files loaded through loader.py)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = ["ImmutablePrompt", "load_prompt", "render"]


# Root directory for versioned prompt files. Resolved relative to this
# module so the loader works from any current working directory.
_PROMPTS_ROOT: Final[Path] = Path(__file__).resolve().parent

# Module-level cache keyed by (version, name). Populated lazily by
# :func:`load_prompt` and never invalidated for the life of the
# process — template files on disk are immutable by design §3.9.
_CACHE: dict[tuple[str, str], "ImmutablePrompt"] = {}

# Regex that locates ``{{KEY}}`` placeholders. ``KEY`` must be a
# non-empty string of uppercase letters, digits, and underscores —
# matches the design §3.9 skeleton's placeholder naming and rejects
# accidental ``{{ not_a_key }}`` forms.
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


@dataclass(frozen=True)
class ImmutablePrompt:
    """A frozen prompt template pinned to a specific version.

    Attributes
    ----------
    version:
        The version folder the template was loaded from (e.g. ``"v1"``).
    name:
        The stem of the template file (e.g. ``"filings_agent"``).
    template:
        Verbatim Markdown text as read from disk, including every
        ``{{KEY}}`` placeholder. Rendering is performed by
        :func:`render`; instances of this dataclass are never mutated.
    """

    version: str
    name: str
    template: str


def load_prompt(version: str, name: str) -> ImmutablePrompt:
    """Load and cache a versioned prompt template from disk.

    Parameters
    ----------
    version:
        The version folder name under ``src/research/prompts/``
        (e.g. ``"v1"``). Must be non-empty.
    name:
        The template file stem (without the ``.md`` suffix), e.g.
        ``"filings_agent"`` for ``filings_agent.md``. Must be
        non-empty.

    Returns
    -------
    ImmutablePrompt
        A frozen dataclass wrapping the verbatim template text.

    Raises
    ------
    ValueError
        If ``version`` or ``name`` is empty or contains path
        separators (guards against directory traversal).
    FileNotFoundError
        If the template file does not exist at the expected path.
    """
    if not version or "/" in version or ".." in version:
        raise ValueError(f"Invalid prompt version: {version!r}")
    if not name or "/" in name or ".." in name:
        raise ValueError(f"Invalid prompt name: {name!r}")

    cache_key = (version, name)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    path = _PROMPTS_ROOT / version / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt template not found: {path}")

    template = path.read_text(encoding="utf-8")
    prompt = ImmutablePrompt(version=version, name=name, template=template)
    _CACHE[cache_key] = prompt
    return prompt


def render(prompt: ImmutablePrompt, *, substitutions: dict[str, str]) -> str:
    """Render a prompt by substituting every ``{{KEY}}`` placeholder.

    Every placeholder found in ``prompt.template`` must have a
    corresponding key in ``substitutions``; a missing key raises
    :class:`KeyError`. This fail-loud behaviour prevents accidental
    blank-substitution of the refusal-policy block or output-schema
    block — both of which are safety-critical (design §3.9, §10.1).

    Parameters
    ----------
    prompt:
        The immutable template loaded via :func:`load_prompt`.
    substitutions:
        Mapping from placeholder key (e.g. ``"REFUSAL_POLICY_BLOCK"``)
        to the verbatim string that replaces it. Extra keys in
        ``substitutions`` that do not appear in the template are
        ignored silently — callers often pass a superset for
        convenience.

    Returns
    -------
    str
        The rendered template with every placeholder replaced. Any
        literal ``{{`` that is not part of a valid placeholder token
        is left untouched.

    Raises
    ------
    KeyError
        If the template contains a ``{{KEY}}`` placeholder that is
        not present in ``substitutions``. The error message includes
        the missing key to aid debugging.
    """

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in substitutions:
            raise KeyError(
                f"Missing substitution for placeholder {{{{{key}}}}} "
                f"in prompt {prompt.version}/{prompt.name}"
            )
        return substitutions[key]

    return _PLACEHOLDER_RE.sub(_replace, prompt.template)


def _reset_cache_for_tests() -> None:
    """Clear the module-level prompt cache.

    Test-only helper — production code MUST NOT call this function.
    The cache is intentionally write-once across a process lifetime;
    the only reason to reset it is to let a test write a fixture
    template to disk and then re-load it through the public API.
    """
    _CACHE.clear()
