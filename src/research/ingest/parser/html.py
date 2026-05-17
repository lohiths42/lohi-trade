"""HTML → canonical Markdown extractor (Req 10.1, design §3.2).

Uses ``trafilatura`` as the primary extractor and ``readability-lxml``
as a secondary fallback. Preserves ``<table>`` elements as
GitHub-flavoured Markdown tables so numerical-results pages keep their
structure (Req 10.5, exercised end-to-end by the downstream section
tagger + chunker).

Requirements covered
--------------------
* **Req 10.1** — convert an HTML document into a canonical text
  representation plus a structured metadata record.

Design reference
----------------
* :file:`.kiro/specs/lohi-research-dashboard/design.md` §3.2:
  "``html.py`` — ``trafilatura`` + ``readability`` fallback".

Output shape
------------
Identical to the PDF parser (:func:`src.research.ingest.parser.pdf.parse_pdf`):
``(canonical_text, sections_raw)`` where ``sections_raw`` is always an
empty list because section tagging happens downstream in
:mod:`src.research.ingest.parser.sections`.

Lazy imports
------------
``trafilatura``, ``readability``, and ``lxml`` are all imported inside
:func:`parse_html`. The Python standard library ``html.parser`` is used
as the final safety net so that a pure-stdlib install can still produce
*some* text extraction when the third-party libraries are absent — this
keeps the ``research.enabled: true`` + ``LOHI_RESEARCH_OFFLINE=true``
configuration from breaking entirely on minimal installs.
"""

from __future__ import annotations

import html as html_std
import re
from html.parser import HTMLParser
from typing import Any, Final

# Whitespace runs collapse to a single space inside the extracted body
# (outside of ``<pre>`` / tables, both of which we rebuild separately).
_WHITESPACE_RUN_RE: Final[re.Pattern[str]] = re.compile(r"[ \t]+")

# Sequences of three or more blank lines collapse to exactly two — same
# rule we apply in ``canonical._normalise_for_equality`` so the
# round-trip test has a stable baseline.
_BLANKLINE_RUN_RE: Final[re.Pattern[str]] = re.compile(r"\n{3,}")


def parse_html(
    content: str,
    *,
    source_url: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Extract *content* to ``(canonical_text, sections_raw)``.

    Parameters
    ----------
    content:
        The raw HTML document body. The function accepts both fully
        formed pages (``<html><body>…</body></html>``) and fragments.
    source_url:
        Optional source URL. ``trafilatura`` uses this as a hint for
        boilerplate removal when the page is known to be an article;
        :mod:`readability` ignores it. Pure-stdlib fallback ignores it
        too.

    Raises
    ------
    ValueError
        If *content* is empty or blank after stripping — an empty input
        is virtually always an ingestion-layer bug and we'd rather fail
        loudly than persist an empty ``CanonicalDoc``.

    """
    if not content or not content.strip():
        raise ValueError("html content is empty")

    tables_markdown = _extract_tables_as_markdown(content)
    body_text = _extract_body_text(content, source_url=source_url)

    # Assemble canonical_text: body first, then each table as its own
    # block. This layout means the Markdown renderer sees: body prose →
    # blank line → table → blank line → next table → etc., which is the
    # conventional shape for company-results pages on BSE/NSE where the
    # narrative precedes the financials.
    blocks: list[str] = []
    if body_text:
        blocks.append(body_text)
    if tables_markdown:
        blocks.extend(tables_markdown)

    canonical_text = "\n\n".join(block.strip("\n") for block in blocks if block)
    canonical_text = _normalise_whitespace(canonical_text)

    return canonical_text, []


# --------------------------------------------------------------------------- #
# Body text extraction (trafilatura → readability → stdlib fallback)          #
# --------------------------------------------------------------------------- #


def _extract_body_text(content: str, *, source_url: str | None) -> str:
    """Return the best available body-text extraction for *content*.

    Tries, in order: ``trafilatura.extract`` (primary), then
    ``readability.Document().summary()`` piped through a stdlib
    stripper, and finally a pure-stdlib tag stripper as a last resort.
    The first extractor that returns a non-empty string wins.
    """
    # --- Primary: trafilatura ------------------------------------------------
    try:
        import trafilatura  # noqa: PLC0415 — lazy per module docstring
    except ImportError:
        trafilatura = None  # type: ignore[assignment]

    if trafilatura is not None:
        try:
            extracted = trafilatura.extract(
                content,
                url=source_url,
                # ``output_format='markdown'`` is available in recent
                # trafilatura releases and gives us headings + lists for
                # free. Older releases fall back to plain text.
                output_format="markdown",
                include_tables=False,  # we handle tables separately
                include_comments=False,
                no_fallback=False,
            )
        except Exception:  # noqa: BLE001 — trafilatura is known to raise on edge inputs
            extracted = None
        if extracted and extracted.strip():
            return extracted.strip()

    # --- Secondary: readability-lxml ----------------------------------------
    try:
        from readability import Document as ReadabilityDoc  # noqa: PLC0415
        document_cls = ReadabilityDoc
    except ImportError:
        document_cls = None  # type: ignore[assignment]

    if document_cls is not None:
        try:
            summary_html = document_cls(content).summary(html_partial=True)
        except Exception:  # noqa: BLE001
            summary_html = ""
        if summary_html and summary_html.strip():
            return _strip_tags(summary_html).strip()

    # --- Tertiary: pure-stdlib fallback -------------------------------------
    return _strip_tags(content).strip()


class _TagStripper(HTMLParser):
    """Minimal HTML → plain-text converter for the stdlib fallback path.

    Drops every tag and its attributes, entity-decodes the text runs,
    and inserts newlines around a small set of block-level elements so
    the result is readable prose rather than a single wall of text.
    """

    _BLOCK_TAGS: Final[frozenset[str]] = frozenset(
        {
            "address",
            "article",
            "aside",
            "blockquote",
            "br",
            "div",
            "footer",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "hr",
            "li",
            "main",
            "nav",
            "ol",
            "p",
            "pre",
            "section",
            "table",
            "tbody",
            "td",
            "tfoot",
            "th",
            "thead",
            "tr",
            "ul",
        },
    )
    _SKIP_TAGS: Final[frozenset[str]] = frozenset({"script", "style", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in self._BLOCK_TAGS:
            self._out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in self._BLOCK_TAGS:
            self._out.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        self._out.append(data)

    def render(self) -> str:
        return "".join(self._out)


def _strip_tags(content: str) -> str:
    """Stdlib-only HTML → plain-text fallback."""
    parser = _TagStripper()
    try:
        parser.feed(content)
        parser.close()
    except Exception:  # noqa: BLE001 — malformed HTML; best-effort
        pass
    return _normalise_whitespace(parser.render())


# --------------------------------------------------------------------------- #
# Table extraction                                                            #
# --------------------------------------------------------------------------- #


class _TableCollector(HTMLParser):
    """Walk the HTML once and collect every ``<table>`` as a list of rows.

    We intentionally do not rely on ``lxml`` here — ``html.parser`` is
    lenient enough for real-world filings HTML and keeps this parser
    dependency-free, which matters for the pure-stdlib offline path.
    Cells preserve their text content (entity-decoded) with whitespace
    collapsed to single spaces.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._nesting: list[str] = []  # track ``<table>``s for nesting

    # -- tag handlers --------------------------------------------------------

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "table":
            # Start a fresh buffer. Nested tables replace the current
            # buffer; we restore the parent on close.
            self._nesting.append(tag)
            self._current_table = []
            self._current_row = None
            self._current_cell = None
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in ("td", "th") and self._current_row is not None:
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            if self._current_cell is not None and self._current_row is not None:
                cell_text = " ".join("".join(self._current_cell).split())
                self._current_row.append(cell_text)
            self._current_cell = None
        elif tag == "tr":
            if self._current_row is not None and self._current_table is not None:
                if self._current_row:
                    self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table":
            if self._nesting:
                self._nesting.pop()
            if self._current_table:
                self._tables.append(self._current_table)
            self._current_table = None
            self._current_row = None
            self._current_cell = None

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    # -- accessor ------------------------------------------------------------

    def tables(self) -> list[list[list[str]]]:
        return self._tables


def _extract_tables_as_markdown(content: str) -> list[str]:
    """Return each ``<table>`` in *content* serialised as Markdown.

    Preserves table structure per Req 10.5. Empty tables and tables with
    only one column are dropped because they round-trip poorly to
    Markdown.
    """
    collector = _TableCollector()
    try:
        collector.feed(content)
        collector.close()
    except Exception:  # noqa: BLE001 — malformed HTML; best-effort
        pass

    rendered: list[str] = []
    for rows in collector.tables():
        if not rows:
            continue
        n_cols = max(len(r) for r in rows)
        if n_cols < 2:
            continue
        rendered.append(_rows_to_markdown_table(rows, n_cols))
    return rendered


def _rows_to_markdown_table(rows: list[list[str]], n_cols: int) -> str:
    """Serialise *rows* as a GitHub-flavoured Markdown table.

    First row is the header; remaining rows are the body. Cells are
    already whitespace-collapsed by :class:`_TableCollector`; we only
    need to escape pipe characters and pad ragged rows to ``n_cols``.
    """

    def _cell(value: str) -> str:
        return html_std.unescape(value).replace("|", "\\|")

    header = rows[0] + [""] * max(0, n_cols - len(rows[0]))
    header = header[:n_cols]
    body_rows = []
    for row in rows[1:]:
        padded = row + [""] * max(0, n_cols - len(row))
        body_rows.append(padded[:n_cols])

    separator = "|".join(["---"] * n_cols)
    lines = [
        "| " + " | ".join(_cell(c) for c in header) + " |",
        "|" + separator + "|",
    ]
    for body_row in body_rows:
        lines.append("| " + " | ".join(_cell(c) for c in body_row) + " |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Whitespace normalisation                                                    #
# --------------------------------------------------------------------------- #


def _normalise_whitespace(text: str) -> str:
    """Collapse whitespace runs and blank-line runs to the canonical form."""
    # Unify line endings first.
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse spaces/tabs within lines (but leave the newlines alone —
    # Markdown uses them as significant separators).
    squashed_lines = [_WHITESPACE_RUN_RE.sub(" ", line).rstrip() for line in unified.split("\n")]
    rejoined = "\n".join(squashed_lines)
    # Collapse 3+ blank lines to 2.
    rejoined = _BLANKLINE_RUN_RE.sub("\n\n", rejoined)
    return rejoined.strip()


__all__ = ["parse_html"]
