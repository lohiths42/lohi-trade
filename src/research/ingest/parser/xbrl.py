"""XBRL → canonical Markdown extractor (Req 10.1, design §3.2).

Thin wrapper around ``arelle`` (the reference open-source XBRL
processor) that flattens an instance document to two blocks:

1. A numerical-facts table — one row per ``(concept, period, unit,
   value)`` tuple, rendered as a GitHub-flavoured Markdown table so the
   downstream chunker and embedder treat it as structured data.
2. A prose block — one Markdown paragraph per text-valued fact
   (``TextBlockItemType`` and friends) so the commentary portion of an
   annual-report XBRL still ends up in embeddings.

Requirements covered
--------------------
* **Req 10.1** — convert an XBRL document into a canonical text
  representation plus a structured metadata record.

Design reference
----------------
* :file:`.kiro/specs/lohi-research-dashboard/design.md` §3.2:
  "``xbrl.py`` — ``arelle`` wrapper".

Heavyweight dependency
----------------------
``arelle`` is a very heavy install (pulls in ``lxml``, ``regex``,
``isodate``, ``openpyxl``, and a few MB of taxonomy cache). We import
it lazily inside :func:`parse_xbrl` and raise a descriptive
:class:`RuntimeError` with a pip-install hint when it is absent — that
way the research package remains importable in stripped-down
environments (offline laptops, minimal CI images) where operators have
not opted into XBRL parsing.

Output shape
------------
Same as the other parsers in this package: ``(canonical_text,
sections_raw)`` with ``sections_raw`` always ``[]`` (section tagging
runs in :mod:`src.research.ingest.parser.sections`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

# Header used in the numerical-facts Markdown table. Centralised so
# property tests in Task 5.14 can import the same constant rather than
# hard-coding the column names.
_NUMERICAL_HEADER: Final[tuple[str, ...]] = (
    "concept",
    "period",
    "unit",
    "value",
)

# Prose-fact concepts that are conventionally stored as ``TextBlockItemType``
# in Indian regulatory taxonomies. We don't hard-filter on this — arelle
# reports ``concept.isTextBlock`` — but keep the reference here for
# readability.
_TEXT_BLOCK_HINTS: Final[frozenset[str]] = frozenset(
    {"TextBlockItemType", "stringItemType"}
)


def parse_xbrl(path: str | Path) -> tuple[str, list[dict[str, Any]]]:
    """Parse the XBRL instance at *path* to canonical Markdown.

    Parameters
    ----------
    path:
        Filesystem path to the XBRL instance document. Arelle handles
        both ``.xml`` instances and ``.xbrl`` files; taxonomy schemas
        are resolved by arelle's bundled package cache.

    Returns
    -------
    tuple
        ``(canonical_text, sections_raw)``. ``canonical_text`` contains
        the numerical Markdown table first (if any facts were numeric)
        followed by a ``## Narrative`` heading and one paragraph per
        text-valued fact. ``sections_raw`` is always ``[]``.

    Raises
    ------
    RuntimeError
        When ``arelle`` cannot be imported. The message includes the
        exact pip package to install so operators have no ambiguity.
    FileNotFoundError
        Propagated from the filesystem layer when *path* does not exist.
    """
    instance_path = Path(path)
    if not instance_path.exists():
        raise FileNotFoundError(f"xbrl instance not found: {instance_path}")

    try:
        # ``arelle`` is distributed on PyPI as ``arelle-release``;
        # importing surfaces its ``Cntlr`` / ``ModelManager`` API.
        from arelle import Cntlr  # noqa: PLC0415 — lazy per module docstring
    except ImportError as exc:
        raise RuntimeError(
            "XBRL parsing requires arelle; pip install arelle-release"
        ) from exc

    controller = Cntlr.Cntlr(logFileName=None)
    try:
        # ``modelXbrl`` lazily loads the taxonomy chain. ``load`` returns
        # ``None`` or a model with ``.modelDocument is None`` on failure.
        model_xbrl = controller.modelManager.load(str(instance_path))
        if model_xbrl is None or getattr(model_xbrl, "modelDocument", None) is None:
            # Delegate to callers via a RuntimeError: the ingestion
            # worker wraps this in a structured parse-error record
            # (see :func:`canonical.parse_error`, Req 10.4).
            raise RuntimeError(
                f"arelle could not load xbrl instance: {instance_path}"
            )

        numerical_rows, text_facts = _partition_facts(model_xbrl)
    finally:
        controller.close()

    blocks: list[str] = []
    if numerical_rows:
        blocks.append("## Facts")
        blocks.append(
            _rows_to_markdown_table(
                [list(_NUMERICAL_HEADER), *numerical_rows]
            )
        )
    if text_facts:
        blocks.append("## Narrative")
        for concept, text in text_facts:
            # One paragraph per fact, preceded by its concept name as a
            # bold lead-in so the chunker can see the boundary.
            blocks.append(f"**{concept}**\n\n{text.strip()}")

    canonical_text = "\n\n".join(b for b in blocks if b)
    return canonical_text, []


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _partition_facts(
    model_xbrl: Any,
) -> tuple[list[list[str]], list[tuple[str, str]]]:
    """Split *model_xbrl*'s facts into numerical rows and text facts.

    Arelle's ``model_xbrl.facts`` yields :class:`ModelFact` instances
    exposing ``concept``, ``contextID``, ``unitID``, and ``xValue`` (the
    typed value). We classify on ``concept.isNumeric`` — a boolean arelle
    pre-computes from the taxonomy — and fall back to duck-typing when
    that attribute is missing (older arelle versions).
    """
    numerical_rows: list[list[str]] = []
    text_facts: list[tuple[str, str]] = []

    for fact in getattr(model_xbrl, "facts", []) or []:
        concept_name = _concept_name(fact)
        period = _format_period(fact)
        unit = _format_unit(fact)
        value = _format_value(fact)

        if _is_numeric_fact(fact):
            numerical_rows.append([concept_name, period, unit, value])
        else:
            if value:
                text_facts.append((concept_name, value))

    return numerical_rows, text_facts


def _is_numeric_fact(fact: Any) -> bool:
    """Return ``True`` if *fact*'s taxonomy concept is numeric."""
    concept = getattr(fact, "concept", None)
    if concept is None:
        return False
    # Arelle exposes ``isNumeric`` directly when the taxonomy is loaded.
    is_numeric = getattr(concept, "isNumeric", None)
    if isinstance(is_numeric, bool):
        return is_numeric
    # Fall back to ``baseXsdType``: numeric types start with
    # ``decimal``/``int``/``long``/``short``/``byte``/``double``/``float``.
    base = getattr(concept, "baseXsdType", "") or ""
    return base.lower().startswith(
        ("decimal", "int", "long", "short", "byte", "double", "float", "monetary")
    )


def _concept_name(fact: Any) -> str:
    """Return the human-readable concept name for *fact*.

    Prefers the qname's local name over the prefixed form because
    embeddings work better on clean identifiers than on ``ns0:``-style
    prefixes.
    """
    concept = getattr(fact, "concept", None)
    if concept is not None:
        qname = getattr(concept, "qname", None)
        local = getattr(qname, "localName", None) if qname is not None else None
        if local:
            return str(local)
    qname = getattr(fact, "qname", None)
    if qname is not None:
        local = getattr(qname, "localName", None)
        if local:
            return str(local)
    return str(getattr(fact, "elementQname", ""))


def _format_period(fact: Any) -> str:
    """Format the context period for a fact as a stable string."""
    context = getattr(fact, "context", None)
    if context is None:
        return ""
    if getattr(context, "isInstantPeriod", False):
        instant = getattr(context, "instantDatetime", None)
        return instant.date().isoformat() if instant is not None else ""
    if getattr(context, "isStartEndPeriod", False):
        start = getattr(context, "startDatetime", None)
        end = getattr(context, "endDatetime", None)
        start_s = start.date().isoformat() if start is not None else ""
        end_s = end.date().isoformat() if end is not None else ""
        return f"{start_s}/{end_s}"
    if getattr(context, "isForeverPeriod", False):
        return "forever"
    return ""


def _format_unit(fact: Any) -> str:
    """Format the unit reference for a fact (empty for non-numeric)."""
    unit = getattr(fact, "unit", None)
    if unit is None:
        return ""
    # ``unit.value`` is a pre-formatted string in arelle (e.g. ``INR`` or
    # ``USD/shares``). Fall back to the unit id if absent.
    value = getattr(unit, "value", None)
    if value:
        return str(value)
    return str(getattr(unit, "id", ""))


def _format_value(fact: Any) -> str:
    """Return the fact's value as a string, handling common edge cases."""
    # ``xValue`` is the typed value when available; ``value`` is the raw
    # string representation. We prefer ``xValue`` for numeric fidelity
    # and fall through to ``value`` for text.
    x_value = getattr(fact, "xValue", None)
    if x_value is not None:
        return str(x_value)
    raw = getattr(fact, "value", None)
    if raw is None:
        return ""
    return str(raw)


def _rows_to_markdown_table(rows: list[list[str]]) -> str:
    """Render *rows* as a GitHub-flavoured Markdown table.

    Duplicated here rather than imported from :mod:`.pdf` / :mod:`.html`
    so each parser is self-contained — the rendering is a five-line
    helper and cross-module imports of private helpers cause surprising
    coupling.
    """
    if not rows:
        return ""
    n_cols = max(len(row) for row in rows)
    if n_cols < 1:
        return ""

    def _cell(value: str) -> str:
        collapsed = " ".join(str(value).split())
        return collapsed.replace("|", "\\|")

    header = rows[0] + [""] * max(0, n_cols - len(rows[0]))
    body = [
        row + [""] * max(0, n_cols - len(row)) for row in rows[1:]
    ]
    separator = "|".join(["---"] * n_cols)
    lines = [
        "| " + " | ".join(_cell(c) for c in header[:n_cols]) + " |",
        "|" + separator + "|",
    ]
    for body_row in body:
        lines.append("| " + " | ".join(_cell(c) for c in body_row[:n_cols]) + " |")
    return "\n".join(lines)


__all__ = ["parse_xbrl"]
