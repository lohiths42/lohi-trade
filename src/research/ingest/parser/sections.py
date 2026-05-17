"""Heading-based section tagger for canonical Markdown (Req 10.6, design §3.2).

Walks a :class:`src.research.ingest.parser.canonical.CanonicalDoc`'s
``canonical_text`` line by line looking for headings, matches each heading
against a config-supplied dictionary of ``{section_name: [phrase, …]}``
aliases, and emits one :class:`SectionSpan` per match so the downstream
pipeline can treat ``management_commentary`` and ``numerical_results``
differently (Req 10.6).

Requirements covered
--------------------
* **Req 10.6** — "detect and tag management-commentary sections
  separately from numerical-results sections using a configurable set of
  section headings".

Design reference
----------------
* :file:`.kiro/specs/lohi-research-dashboard/design.md` §3.2 names this
  module "``sections.py`` — management-commentary vs results heading
  tagger (Req 10.6)".

How it works
------------
A *heading* is any of the following line shapes:

1. A Markdown ATX heading — one to six ``#`` characters, a space, then a
   non-empty title on a single line (e.g. ``## Management Discussion``).
2. A Markdown Setext heading — a non-empty title line followed
   immediately by a line of at least three ``=`` or ``-`` characters.
3. An all-caps / title-case line sitting on its own between blank lines
   and matching one of the configured alias phrases (common in scanned
   PDFs where the PDF parser has flattened the formatting).

Each heading is lower-cased, stripped of punctuation, and checked
against every alias in the config. The **first** matching
``section_name`` wins (so operators can prioritise specific aliases by
ordering the dict). For each heading we emit a span that runs from the
*line offset* of the heading through either the *line offset* of the
next recognised heading or the end of the document, whichever comes
first.

Non-goals
---------
* We do not parse heading *content* — this stage only records spans.
* We do not deduplicate against later stages — the
  :class:`~src.research.ingest.parser.canonical.CanonicalDoc` validator
  rejects duplicate section names, so callers that need to merge (for
  example, two "Management Discussion" headings separated by a
  title page) must do so before constructing the model.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from .canonical import SectionSpan

# --------------------------------------------------------------------------- #
# Default heading aliases                                                     #
# --------------------------------------------------------------------------- #

DEFAULT_SECTION_HEADINGS: Final[dict[str, list[str]]] = {
    "management_commentary": [
        "management discussion",
        "management discussion and analysis",
        "management's discussion and analysis",
        "md&a",
        "directors report",
        "directors' report",
        "chairman's letter",
        "chairman's statement",
        "letter to shareholders",
        "managing director's review",
        "ceo's message",
    ],
    "numerical_results": [
        "results",
        "financial results",
        "statement of profit and loss",
        "statement of profit & loss",
        "profit and loss",
        "balance sheet",
        "statement of financial position",
        "cash flow statement",
        "statement of cash flows",
        "key financial highlights",
    ],
    "shareholding": [
        "shareholding pattern",
        "pattern of shareholding",
        "statement of shareholding",
    ],
    "auditor_report": [
        "auditor's report",
        "independent auditor's report",
        "auditors' report",
    ],
    "notes_to_accounts": [
        "notes to accounts",
        "notes to the financial statements",
        "notes forming part of the financial statements",
    ],
}
"""Lower-case alias phrases for the canonical Indian corporate-filing
sections. Aliases are matched against the normalised heading text via
substring containment, so a heading like "Management Discussion and
Analysis (standalone)" still maps to ``management_commentary``.

Callers can pass their own mapping to :func:`tag_sections`; passing
``None`` or an empty dict falls back to this default.
"""


# ATX headings: one to six ``#``, a space, a non-empty title.
_ATX_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<hashes>#{1,6})[ \t]+(?P<title>\S.*?)[ \t]*#*[ \t]*$",
)

# Setext underline: three or more ``=`` or ``-`` characters on their own.
_SETEXT_UNDERLINE_RE: Final[re.Pattern[str]] = re.compile(r"^[ \t]*(=|-){3,}[ \t]*$")

# All-caps line heuristic: at least three letters, no lowercase letters,
# optionally containing spaces / digits / basic punctuation. We keep this
# deliberately tight to avoid flagging prose.
_ALLCAPS_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*(?=.*[A-Z]{3,})[A-Z0-9 &'().,:\-/]+[ \t]*$",
)

# Punctuation we strip from a heading before matching aliases. We keep
# ampersands and apostrophes because some aliases rely on them ("MD&A",
# "chairman's"); they're removed below via ``_normalise_heading``.
_HEADING_STRIP_RE: Final[re.Pattern[str]] = re.compile(r"[^\w\s]")


def _normalise_heading(raw: str) -> str:
    """Lower-case + collapse whitespace + drop punctuation, for alias match.

    The aliases in :data:`DEFAULT_SECTION_HEADINGS` are stored in their
    "natural" form (``"chairman's letter"``, ``"md&a"``, etc.) and
    normalised through this same function at match time so both sides
    share one representation.
    """
    lowered = raw.lower()
    stripped = _HEADING_STRIP_RE.sub(" ", lowered)
    return " ".join(stripped.split())


def _match_section_name(
    normalised: str,
    headings_config: dict[str, list[str]],
) -> str | None:
    """Return the first section name whose alias list matches *normalised*.

    Matching is substring containment on the normalised heading *and* the
    normalised alias — this tolerates trailing qualifiers ("Results for
    the quarter ended 30 June 2024") while still rejecting unrelated
    prose.
    """
    for section_name, aliases in headings_config.items():
        for alias in aliases:
            alias_norm = _normalise_heading(alias)
            if alias_norm and alias_norm in normalised:
                return section_name
    return None


def _iter_heading_lines(
    lines: list[str],
) -> Iterable[tuple[int, str]]:
    """Yield ``(line_index, raw_heading_text)`` pairs in source order.

    Walks the line list once, recognising the three heading shapes
    described in the module docstring. Setext headings consume two
    source lines; all-caps headings must be sandwiched between blank
    lines (or the file boundary) so that body text never qualifies.
    """
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        atx = _ATX_RE.match(line)
        if atx:
            yield i, atx.group("title").strip()
            i += 1
            continue

        # Setext: current line has text, next line is an underline.
        if line.strip() and i + 1 < n and _SETEXT_UNDERLINE_RE.match(lines[i + 1]):
            yield i, line.strip()
            i += 2
            continue

        # All-caps heuristic: text line with no lowercase letters,
        # surrounded by blank lines (or the file start/end).
        prev_blank = i == 0 or not lines[i - 1].strip()
        next_blank = i + 1 >= n or not lines[i + 1].strip()
        if prev_blank and next_blank and _ALLCAPS_RE.match(line):
            yield i, line.strip()
            i += 1
            continue

        i += 1


def tag_sections(
    canonical_text: str,
    headings_config: dict[str, list[str]] | None = None,
) -> list[SectionSpan]:
    """Return the list of :class:`SectionSpan`s detected in *canonical_text*.

    Parameters
    ----------
    canonical_text:
        The Markdown body of a
        :class:`src.research.ingest.parser.canonical.CanonicalDoc`. This
        is the ``canonical_text`` **without** the HTML section markers
        (those are a pretty-printing concern); callers either work with
        a freshly-parsed PDF/HTML/XBRL file or the ``canonical_text``
        attribute of an already-parsed :class:`CanonicalDoc`.
    headings_config:
        Optional ``{section_name: [alias_phrase, …]}`` mapping. When
        ``None`` or empty the function uses
        :data:`DEFAULT_SECTION_HEADINGS`.

    Notes
    -----
    * Spans cover ``[heading_line_start, next_heading_line_start)`` in
      character offsets (inclusive start, exclusive end), so they are
      directly usable in :attr:`CanonicalDoc.sections`.
    * The returned list is sorted by ``start`` and contains at most one
      entry per unique ``section_name`` — duplicates from repeated
      headings collapse to the *first* occurrence, because
      :class:`CanonicalDoc` rejects duplicate section names. If you need
      the *union* of multiple headings for the same section, merge
      manually after calling this function.
    * An empty input returns an empty list; an input with no
      recognisable headings also returns an empty list (a plain
      document is valid, it simply has no tagged sections).

    """
    if not canonical_text:
        return []

    config = headings_config or DEFAULT_SECTION_HEADINGS

    # Pre-compute the character offset at the start of each line so we
    # can translate line indexes to ``canonical_text`` offsets in O(1).
    lines = canonical_text.split("\n")
    line_offsets: list[int] = []
    running = 0
    for line in lines:
        line_offsets.append(running)
        running += len(line) + 1  # +1 for the stripped '\n'
    # Sentinel: the offset one past the last character so the last
    # heading's span can extend to EOF.
    eof_offset = len(canonical_text)

    # First pass: collect raw headings with their matched section names.
    matches: list[tuple[int, str]] = []  # (line_index, section_name)
    for line_index, raw_heading in _iter_heading_lines(lines):
        normalised = _normalise_heading(raw_heading)
        if not normalised:
            continue
        section_name = _match_section_name(normalised, config)
        if section_name is None:
            continue
        matches.append((line_index, section_name))

    if not matches:
        return []

    # Second pass: convert to SectionSpans. Each span runs from the
    # heading's line offset to the next matched heading's line offset
    # (or EOF). Duplicate section names after the first are dropped
    # because :class:`CanonicalDoc` rejects duplicates.
    spans: list[SectionSpan] = []
    seen_names: set[str] = set()
    for idx, (line_index, section_name) in enumerate(matches):
        if section_name in seen_names:
            continue
        seen_names.add(section_name)
        start_offset = line_offsets[line_index]
        if idx + 1 < len(matches):
            next_line_index = matches[idx + 1][0]
            end_offset = line_offsets[next_line_index]
        else:
            end_offset = eof_offset
        spans.append(
            SectionSpan(name=section_name, start=start_offset, end=end_offset),
        )

    # Sort by start offset. ``matches`` is already in source order, and
    # dropping duplicates preserves that order, but sort defensively so
    # any future reordering of ``matches`` does not break callers.
    spans.sort(key=lambda s: s.start)
    return spans


__all__ = [
    "DEFAULT_SECTION_HEADINGS",
    "tag_sections",
]
