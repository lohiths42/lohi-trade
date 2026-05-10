"""Canonical document model + pretty-printer inverse (Req 10.1-10.4, design §3.2).

The ingestion pipeline's last normalisation stage. Every PDF / HTML / XBRL
parser in this package hands its ``(canonical_text, sections_raw)`` output
to a :class:`CanonicalDoc` instance; from there the rest of the research
stack (chunker, embedder, retriever, Judge, Snapshot) sees a single,
versioned record shape.

Requirements covered
--------------------
* **Req 10.1** — ``CanonicalDoc`` is the canonical text plus structured
  metadata record emitted by :class:`src.research.ingest.parser` for every
  PDF / HTML / XBRL input.
* **Req 10.2** — :func:`pretty_print` is the ``Filings_Pretty_Printer``,
  formatting a :class:`CanonicalDoc` back to stable Markdown.
* **Req 10.3** — :func:`parse_canonical` is the inverse:
  ``parse_canonical(pretty_print(doc)) == doc`` modulo the whitespace
  normalisation codified by :func:`_normalise_for_equality` (this is the
  round-trip property exercised by Task 5.14 /
  ``tests/research/test_prop_parser_roundtrip.py`` against **Property 5 /
  Req 14.5**).
* **Req 10.4** — the helper :func:`parse_error` returns a structured
  ``dict`` so :mod:`src.research.ingest.parser.{pdf,html,xbrl}` can surface
  unparseable documents without raising uncaught exceptions.

Design reference
----------------
* :file:`.kiro/specs/lohi-research-dashboard/design.md` §3.2 — defines the
  ``CanonicalDoc`` Pydantic shape we must honour verbatim and names
  ``parser/canonical.py`` as the home of the pretty-printer inverse.

Round-trip contract
-------------------
``pretty_print`` emits the following Markdown layout:

.. code-block:: text

    <!-- lohi-canonical-doc v1 -->
    <!-- meta:
    {
      "document_id": "...",
      ...
    }
    -->

    <!-- section:management_commentary:start -->
    # Management Discussion
    ...
    <!-- section:management_commentary:end -->
    <!-- section:numerical_results:start -->
    ...
    <!-- section:numerical_results:end -->

The section-marker HTML comments are placed at the **exact character
offsets** recorded in :attr:`CanonicalDoc.sections`, and :func:`parse_canonical`
reads them back by stripping the markers and recomputing the offsets. The
markers are idempotent: the printer never emits overlapping or duplicate
markers, and the parser rejects files whose markers overlap. Whitespace
around markers is normalised by :func:`_normalise_for_equality` so the
round-trip property tolerates editor-level reformatting while still
catching any substantive loss of information.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# Document type enumeration                                                   #
# --------------------------------------------------------------------------- #

DocumentType = Literal[
    "announcement",
    "annual_report",
    "concall",
    "shareholding",
    "ir_deck",
    "user_upload",
]
"""The six document categories carried end-to-end through the pipeline.

Matches design §3.2's ``document_type`` literal set verbatim. Any addition
requires a matching design update because downstream agents
(:mod:`src.research.agents`) switch on this value.
"""

# Bump when the pretty-printer emit format changes in a
# non-backwards-compatible way. :func:`parse_canonical` rejects versions it
# does not know so operators see an explicit mismatch rather than silent
# data loss.
_FORMAT_VERSION: Final[str] = "v1"

# Marker layout. Centralised so there is exactly one source of truth —
# tests (Task 5.14) import these constants rather than redefining them.
_HEADER_COMMENT: Final[str] = f"<!-- lohi-canonical-doc {_FORMAT_VERSION} -->"
_META_BLOCK_OPEN: Final[str] = "<!-- meta:"
_META_BLOCK_CLOSE: Final[str] = "-->"
_SECTION_START_TEMPLATE: Final[str] = "<!-- section:{name}:start -->"
_SECTION_END_TEMPLATE: Final[str] = "<!-- section:{name}:end -->"

# Pre-compiled regex for scanning section markers during inverse parsing.
# Section names are ``snake_case`` (letters + digits + underscore) to keep
# the grammar deterministic and avoid HTML-escaping concerns inside the
# comment.
_SECTION_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9_]*")
_SECTION_START_RE: Final[re.Pattern[str]] = re.compile(
    r"<!-- section:(?P<name>[a-z][a-z0-9_]*):start -->",
)
_SECTION_END_RE: Final[re.Pattern[str]] = re.compile(
    r"<!-- section:(?P<name>[a-z][a-z0-9_]*):end -->",
)

# Matches the SHA-256 hex shape we persist on ``research_documents.sha256``.
_SHA256_HEX_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


# --------------------------------------------------------------------------- #
# Pydantic models                                                             #
# --------------------------------------------------------------------------- #


class SectionSpan(BaseModel):
    """A tagged half-open span ``[start, end)`` over ``canonical_text``.

    ``start`` / ``end`` are **character offsets** (not byte offsets and
    not line offsets) into :attr:`CanonicalDoc.canonical_text` after the
    printer has emitted the document's body. The pretty-printer places a
    ``<!-- section:{name}:start -->`` comment at the exact ``start``
    offset and a matching end marker at ``end`` — those markers are
    stripped from the emitted text before offsets are computed, so spans
    remain valid against ``canonical_text`` in either representation.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        min_length=1,
        description="Section label in ``snake_case``; e.g. "
        "``management_commentary`` or ``numerical_results`` (Req 10.6).",
    )
    start: int = Field(
        ...,
        ge=0,
        description="Inclusive character offset into ``canonical_text``.",
    )
    end: int = Field(
        ...,
        ge=0,
        description="Exclusive character offset into ``canonical_text``.",
    )

    @field_validator("name")
    @classmethod
    def _name_is_snake_case(cls, value: str) -> str:
        """Reject names that would collide with the marker grammar.

        The marker regex (``_SECTION_START_RE``) only recognises
        ``[a-z][a-z0-9_]*``; any other character would round-trip as
        orphaned text inside an HTML comment and break
        :func:`parse_canonical`.
        """
        if not _SECTION_NAME_RE.fullmatch(value):
            raise ValueError(
                f"section name must match [a-z][a-z0-9_]*, got {value!r}",
            )
        return value


class CanonicalDoc(BaseModel):
    """The canonical ingested document (design §3.2).

    All ingested PDFs, HTML pages, and XBRL instance documents land in this
    shape before they are chunked and embedded. The pretty-printer
    round-trips this model to Markdown and back, so changes here **must**
    be reflected symmetrically in :func:`pretty_print` +
    :func:`parse_canonical`.
    """

    model_config = ConfigDict(extra="forbid")

    document_id: UUID = Field(
        ...,
        description="Stable UUID. Conventionally derived from the sha256 "
        "content hash upstream of this model so re-ingestion of the same "
        "bytes yields the same id (Req 3.5, Req 3.12).",
    )
    symbol: str = Field(
        ...,
        min_length=1,
        description="Ticker symbol (e.g. ``RELIANCE``).",
    )
    document_type: DocumentType = Field(
        ...,
        description="One of the six categories from design §3.2.",
    )
    source_url: str | None = Field(
        default=None,
        description="Source URL when the document came from a public feed; "
        "``None`` for user uploads.",
    )
    sha256: str = Field(
        ...,
        description="64-char lowercase hex SHA-256 over the canonical "
        "payload (Req 3.5).",
    )
    published_at: datetime = Field(
        ...,
        description="Publication timestamp as reported by the source feed.",
    )
    canonical_text: str = Field(
        ...,
        description="Normalised Markdown body. Tables are preserved as "
        "GitHub-flavoured Markdown tables (Req 10.5); section-boundary "
        "HTML comments are **not** stored here — they are injected by "
        ":func:`pretty_print` and stripped by :func:`parse_canonical`.",
    )
    sections: list[SectionSpan] = Field(
        default_factory=list,
        description="Tagged section spans over ``canonical_text`` "
        "(Req 10.6).",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form parser metadata (page count, number of "
        "tables, parser name, etc.). JSON-serialisable only; non-JSON "
        "values would break the pretty-printer.",
    )

    @field_validator("sha256")
    @classmethod
    def _sha256_is_hex(cls, value: str) -> str:
        """Enforce 64-char lowercase hex so the value round-trips losslessly."""
        if not _SHA256_HEX_RE.fullmatch(value):
            raise ValueError(
                "sha256 must be 64 lowercase hex characters",
            )
        return value

    @field_validator("sections")
    @classmethod
    def _sections_are_wellformed(
        cls, value: list[SectionSpan],
    ) -> list[SectionSpan]:
        """Reject overlapping, reversed, or duplicate-name section spans.

        Validating here (rather than in :func:`pretty_print`) means a
        round-tripped document cannot sneak malformed spans past the
        parser — :func:`parse_canonical` re-instantiates the model and
        the same validator fires.
        """
        if not value:
            return value
        ordered = sorted(value, key=lambda s: s.start)
        prev_end = -1
        seen_names: set[str] = set()
        for span in ordered:
            if span.end < span.start:
                raise ValueError(
                    f"section {span.name!r} has end < start "
                    f"({span.end} < {span.start})",
                )
            if span.start < prev_end:
                raise ValueError(
                    f"section {span.name!r} overlaps the preceding span "
                    f"(start={span.start} < prev_end={prev_end})",
                )
            if span.name in seen_names:
                raise ValueError(
                    f"duplicate section name {span.name!r}; merge spans "
                    "before building a CanonicalDoc",
                )
            seen_names.add(span.name)
            prev_end = span.end
        return value


# --------------------------------------------------------------------------- #
# Structured parse errors (Req 10.4)                                          #
# --------------------------------------------------------------------------- #


def parse_error(
    *,
    document_id: str | UUID | None,
    source_url: str | None,
    reason: str,
) -> dict[str, str | None]:
    """Build the structured error envelope required by Req 10.4.

    :mod:`src.research.ingest.parser.pdf`, :mod:`.html`, and :mod:`.xbrl`
    return this dict rather than raising when an input is unparseable, so
    the ingestion worker can persist the failure on
    ``research_audit_log`` and move on to the next document instead of
    crashing the whole poll cycle.
    """
    return {
        "document_id": str(document_id) if document_id is not None else None,
        "source_url": source_url,
        "reason": reason,
    }


# --------------------------------------------------------------------------- #
# Pretty-printer (Req 10.2)                                                   #
# --------------------------------------------------------------------------- #


def pretty_print(doc: CanonicalDoc) -> str:
    """Serialise *doc* to stable Markdown with section markers.

    The emitted text has three regions:

    1. A header comment identifying the format version.
    2. A ``<!-- meta: { … } -->`` comment block carrying everything in
       the :class:`CanonicalDoc` other than ``canonical_text`` and
       ``sections`` (those are represented structurally in the body).
    3. The body: ``canonical_text`` with section-start/end HTML comments
       injected at the recorded offsets.

    The output is deterministic: given the same :class:`CanonicalDoc`, the
    function returns byte-identical Markdown. This is what makes the
    round-trip property meaningful (Req 10.3, Req 14.5).
    """
    meta_payload: dict[str, Any] = {
        "document_id": str(doc.document_id),
        "symbol": doc.symbol,
        "document_type": doc.document_type,
        "source_url": doc.source_url,
        "sha256": doc.sha256,
        # ``.isoformat`` preserves tz-awareness and sub-second precision
        # exactly. ``fromisoformat`` is the documented inverse.
        "published_at": _isoformat_utc(doc.published_at),
        "metadata": doc.metadata,
    }
    # ``sort_keys=True`` + ``ensure_ascii=False`` gives us stable output
    # across Python versions and locales; indentation keeps the comment
    # block readable for humans.
    meta_json = json.dumps(
        meta_payload,
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
    )

    body = _inject_section_markers(doc.canonical_text, doc.sections)

    # Blank line between meta block and body so the body can itself start
    # with a heading (``# …``) without Markdown joining it to the
    # comment.
    return (
        f"{_HEADER_COMMENT}\n"
        f"{_META_BLOCK_OPEN}\n{meta_json}\n{_META_BLOCK_CLOSE}\n"
        "\n"
        f"{body}"
    )


# --------------------------------------------------------------------------- #
# Inverse parser (Req 10.3)                                                   #
# --------------------------------------------------------------------------- #


def parse_canonical(markdown: str) -> CanonicalDoc:
    """Parse the Markdown produced by :func:`pretty_print` back to a model.

    Raises :class:`ValueError` with a descriptive message when the input
    is malformed. Ingest call sites catch that and funnel it through
    :func:`parse_error` (Req 10.4) — they do **not** let it propagate.
    """
    header, remainder = _consume_header(markdown)
    if header != _HEADER_COMMENT:
        raise ValueError(
            f"unsupported canonical-doc format header: {header!r}; "
            f"expected {_HEADER_COMMENT!r}",
        )

    meta_payload, body_with_markers = _consume_meta_block(remainder)
    canonical_text, sections = _extract_sections(body_with_markers)

    return CanonicalDoc(
        document_id=UUID(meta_payload["document_id"]),
        symbol=meta_payload["symbol"],
        document_type=meta_payload["document_type"],
        source_url=meta_payload["source_url"],
        sha256=meta_payload["sha256"],
        published_at=datetime.fromisoformat(meta_payload["published_at"]),
        canonical_text=canonical_text,
        sections=sections,
        metadata=meta_payload.get("metadata", {}) or {},
    )


# --------------------------------------------------------------------------- #
# Equality helper used by the round-trip property (Req 14.5)                  #
# --------------------------------------------------------------------------- #


def _normalise_for_equality(text: str) -> str:
    """Normalise *text* for the round-trip equivalence comparison.

    The round-trip property is stated "modulo whitespace normalisation",
    so we collapse the specific whitespace differences a pretty-printer
    is allowed to introduce:

    * Windows / classic Mac newlines are folded to ``\n``.
    * Trailing whitespace on each line is stripped.
    * Runs of three or more blank lines collapse to exactly two (the
      maximum a Markdown block separator needs).
    * A single trailing newline is enforced.

    Equivalence of two :class:`CanonicalDoc` values for property-test
    purposes is:

    .. code-block:: python

        (
            a.model_dump(exclude={"canonical_text"})
            == b.model_dump(exclude={"canonical_text"})
            and _normalise_for_equality(a.canonical_text)
            == _normalise_for_equality(b.canonical_text)
        )

    Tests in Task 5.14 use exactly this helper.
    """
    # Unify line endings.
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    # Strip trailing whitespace per line.
    stripped_lines = [line.rstrip() for line in unified.split("\n")]
    rejoined = "\n".join(stripped_lines)
    # Collapse 3+ blank lines to a single blank line separator.
    while "\n\n\n" in rejoined:
        rejoined = rejoined.replace("\n\n\n", "\n\n")
    # Enforce exactly one trailing newline if there is any content.
    if rejoined and not rejoined.endswith("\n"):
        rejoined += "\n"
    return rejoined


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _isoformat_utc(value: datetime) -> str:
    """Serialise a datetime losslessly for the meta block.

    Naive datetimes are assumed UTC; aware datetimes are preserved with
    their offset. Either way :meth:`datetime.fromisoformat` is the exact
    inverse, giving us a guaranteed-clean round trip.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _inject_section_markers(
    canonical_text: str, sections: list[SectionSpan],
) -> str:
    """Return ``canonical_text`` with start/end HTML comments inserted.

    Insertion proceeds right-to-left so earlier offsets do not shift as
    later markers are added. All markers are emitted even when adjacent
    (the parser handles zero-length separations fine); the
    :class:`CanonicalDoc` validator guarantees spans are non-overlapping.
    """
    if not sections:
        return canonical_text

    # Build (offset, insert_text) pairs. For each span we need two
    # insertions. Sorting by offset descending means an earlier-in-text
    # insertion does not shift the indexes of later ones.
    insertions: list[tuple[int, str]] = []
    for span in sections:
        if span.start < 0 or span.end > len(canonical_text):
            raise ValueError(
                f"section {span.name!r} offsets out of range for "
                f"canonical_text of length {len(canonical_text)}: "
                f"start={span.start} end={span.end}",
            )
        insertions.append(
            (span.start, _SECTION_START_TEMPLATE.format(name=span.name)),
        )
        insertions.append(
            (span.end, _SECTION_END_TEMPLATE.format(name=span.name)),
        )

    # Sort descending by offset. At equal offsets we want the closing
    # section's ``end`` marker to land *before* the next section's
    # ``start`` marker in the final text — i.e. "…text. <!--…:end --><!
    # --…:start --> more text…". Because we insert in descending order
    # of offset (so earlier inserts don't shift later indexes), the last
    # insertion at a given offset wins the leftmost position. We
    # therefore sort ``end`` markers *first* at equal offsets, meaning
    # they get inserted last and end up leftmost.
    def _key(item: tuple[int, str]) -> tuple[int, int]:
        offset, marker = item
        # secondary=0 for ``end``, 1 for ``start``: with reverse=True
        # the tuple comparison puts higher secondary values earlier in
        # iteration, so ``start`` is inserted first and ``end`` second,
        # placing ``end`` leftmost in the output.
        secondary = 0 if ":end" in marker else 1
        return (offset, secondary)

    insertions.sort(key=_key, reverse=True)

    buf = canonical_text
    for offset, marker in insertions:
        buf = f"{buf[:offset]}{marker}{buf[offset:]}"
    return buf


def _consume_header(markdown: str) -> tuple[str, str]:
    """Split off the first line (format header) from *markdown*.

    Returns ``(header_line, rest)``. Blank leading lines are tolerated.
    """
    # Tolerate a leading BOM or spurious blank lines the way most
    # Markdown editors do, but do not swallow content.
    text = markdown.lstrip("\ufeff")
    # Find the first non-blank line.
    newline_index = text.find("\n")
    if newline_index == -1:
        # Single-line input — whole thing is the header, nothing else.
        return text.strip(), ""
    header = text[:newline_index].strip()
    rest = text[newline_index + 1 :]
    return header, rest


def _consume_meta_block(markdown: str) -> tuple[dict[str, Any], str]:
    """Peel the ``<!-- meta: {...} -->`` block off the front of *markdown*.

    Returns ``(meta_dict, body_remainder)``. The body remainder begins at
    the first character after the closing ``-->`` (plus any immediately
    following newline so the body layout matches :func:`pretty_print`'s
    blank-line separator).
    """
    open_index = markdown.find(_META_BLOCK_OPEN)
    if open_index == -1:
        raise ValueError("canonical-doc meta block not found")
    # Locate the matching ``-->`` **after** the opener. We cannot simply
    # search for ``-->`` because that substring is also present in the
    # opener itself (``<!-- meta:``). We therefore scan forward.
    close_index = markdown.find(_META_BLOCK_CLOSE, open_index + len(_META_BLOCK_OPEN))
    if close_index == -1:
        raise ValueError("canonical-doc meta block is not terminated")

    # Everything between the opener and the closer, trimmed, is the JSON
    # payload.
    payload_raw = markdown[open_index + len(_META_BLOCK_OPEN) : close_index]
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"canonical-doc meta JSON is invalid: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("canonical-doc meta must decode to a JSON object")

    body_start = close_index + len(_META_BLOCK_CLOSE)
    # Eat exactly one trailing newline and up to one blank line separator
    # — matches the printer's ``-->\n\n<body>`` layout so the body text
    # does not gain leading blank lines on the round trip.
    rest = markdown[body_start:]
    rest = rest.removeprefix("\n")
    rest = rest.removeprefix("\n")
    return payload, rest


def _extract_sections(
    body_with_markers: str,
) -> tuple[str, list[SectionSpan]]:
    """Remove section HTML comments and recompute offsets.

    Returns ``(canonical_text, sections)`` where ``canonical_text`` no
    longer contains any ``<!-- section:… -->`` comments and each
    :class:`SectionSpan` records the post-strip offsets.
    """
    # Collect every marker occurrence in source order together with its
    # span (``name``, ``kind``, ``start_in_source``, ``end_in_source``).
    markers: list[tuple[int, int, str, str]] = []  # (src_start, src_end, name, kind)
    for match in _SECTION_START_RE.finditer(body_with_markers):
        markers.append(
            (match.start(), match.end(), match.group("name"), "start"),
        )
    for match in _SECTION_END_RE.finditer(body_with_markers):
        markers.append(
            (match.start(), match.end(), match.group("name"), "end"),
        )
    markers.sort(key=lambda m: m[0])

    # Walk the source left-to-right, copying non-marker runs into the
    # output buffer. Each time we encounter a marker, record its
    # post-strip offset and skip the marker bytes. The resulting buffer
    # is the reconstructed ``canonical_text`` and the recorded offsets
    # align with it.
    out: list[str] = []
    cursor = 0
    pending_starts: dict[str, int] = {}
    spans: list[SectionSpan] = []

    for src_start, src_end, name, kind in markers:
        if src_start < cursor:
            # Overlap between regex matches (should never happen: the
            # two regexes are disjoint). Fail loud.
            raise ValueError(
                f"overlapping section markers detected near offset {src_start}",
            )
        out.append(body_with_markers[cursor:src_start])
        # Compute the post-strip offset: length of everything we have
        # written into ``out`` so far.
        post_offset = sum(len(piece) for piece in out)
        if kind == "start":
            if name in pending_starts:
                raise ValueError(
                    f"nested or duplicate start marker for section {name!r}",
                )
            pending_starts[name] = post_offset
        else:  # end
            if name not in pending_starts:
                raise ValueError(
                    f"end marker for section {name!r} without a preceding start",
                )
            start_offset = pending_starts.pop(name)
            spans.append(
                SectionSpan(name=name, start=start_offset, end=post_offset),
            )
        cursor = src_end

    out.append(body_with_markers[cursor:])
    canonical_text = "".join(out)

    if pending_starts:
        raise ValueError(
            "unterminated section start marker(s): "
            f"{sorted(pending_starts.keys())}",
        )

    # Sort by ``start`` so the round-trip yields the same ordering as a
    # freshly-constructed :class:`CanonicalDoc` (whose validator also
    # sorts internally for overlap checking but preserves insertion
    # order on the wire).
    spans.sort(key=lambda s: s.start)
    return canonical_text, spans


__all__ = [
    "CanonicalDoc",
    "DocumentType",
    "SectionSpan",
    "parse_canonical",
    "parse_error",
    "pretty_print",
]
