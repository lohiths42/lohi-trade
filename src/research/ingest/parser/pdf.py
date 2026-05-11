"""PDF → canonical Markdown extractor (Req 10.1, Req 10.5, design §3.2).

Thin wrapper around ``pypdf`` with an optional ``pdfplumber`` fallback for
pages whose layout is table-heavy. Produces the ``(canonical_text,
sections_raw)`` shape consumed by the section tagger
(:mod:`src.research.ingest.parser.sections`) and the
:class:`~src.research.ingest.parser.canonical.CanonicalDoc` assembler.

Requirements covered
--------------------
* **Req 10.1** — convert a PDF document into a canonical text
  representation plus a structured metadata record.
* **Req 10.5** — preserve table structure for tabular data (results,
  shareholding patterns) as Markdown tables in the canonical
  representation.

Design reference
----------------
* :file:`.kiro/specs/lohi-research-dashboard/design.md` §3.2:
  "``pdf.py`` — ``pypdf`` + layout-preserving text extraction".
* Design Open Issue #5 authorises the ``pdfplumber`` fallback for
  tabular pages when ``pypdf`` yields sparse text.

Behaviour
---------
1. Open the document with ``pypdf`` and extract each page's text.
2. If a page's extracted text is "sparse" (below
   :data:`_SPARSE_CHAR_THRESHOLD` characters) we attempt a
   ``pdfplumber`` extraction on the same page. When ``pdfplumber``
   identifies at least one table we serialise each table as a
   GitHub-flavoured Markdown table and append it to the page text.
3. Concatenate all page Markdown with a blank-line separator
   (``"\\n\\n"``). This is the ``canonical_text`` returned to the
   caller.
4. ``sections_raw`` is always ``[]``: section tagging is the
   responsibility of :mod:`.sections`, which runs downstream on the
   concatenated text.

Lazy imports
------------
``pypdf`` and ``pdfplumber`` are imported **inside** :func:`parse_pdf`
rather than at module import time so the research package stays usable
in environments that have not installed the optional parser extras
(Req 9.1 — offline default). A missing ``pypdf`` raises
:class:`RuntimeError` with a pip-install hint; a missing
``pdfplumber`` simply disables the fallback without affecting the
happy path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

# Character count below which we consider a ``pypdf`` page extraction
# "sparse" and worth a ``pdfplumber`` retry. Chosen empirically — a page
# of flowing prose typically yields >800 chars, whereas a page that is
# mostly a table commonly extracts as <200 under ``pypdf``. Tunable by
# operators who ship richer pages.
_SPARSE_CHAR_THRESHOLD: Final[int] = 200

# Separator between page Markdown blocks in ``canonical_text``. One blank
# line keeps Markdown renderers happy (headings and tables are treated
# as their own block) without introducing false "section boundary" noise
# for the section tagger.
_PAGE_SEPARATOR: Final[str] = "\n\n"


def parse_pdf(path: str | Path) -> tuple[str, list[dict[str, Any]]]:
    """Extract a PDF at *path* to ``(canonical_text, sections_raw)``.

    The returned tuple mirrors every parser in this package so the
    ingestion worker can treat them uniformly. ``sections_raw`` is
    always an empty list here — section tagging runs downstream in
    :func:`src.research.ingest.parser.sections.tag_sections`.

    Raises
    ------
    RuntimeError
        If ``pypdf`` is not importable in the current environment. The
        message points operators at the exact pip package to install.
    FileNotFoundError
        Propagated from the filesystem layer when *path* does not exist.

    """
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"pdf file not found: {pdf_path}")

    try:
        import pypdf  # noqa: PLC0415 — lazy per module docstring
    except ImportError as exc:
        raise RuntimeError(
            "PDF parsing requires pypdf; pip install pypdf",
        ) from exc

    # pdfplumber is an *optional* fallback — we never hard-require it.
    try:
        import pdfplumber  # noqa: PLC0415 — lazy per module docstring
        pdfplumber_available: bool = True
    except ImportError:
        pdfplumber = None  # type: ignore[assignment]
        pdfplumber_available = False

    # ``pypdf.PdfReader`` accepts a path-like or a binary stream.
    reader = pypdf.PdfReader(str(pdf_path))

    # Cache pdfplumber's open document so we don't re-open per page.
    # Opened lazily on first sparse page.
    plumber_doc = None

    page_blocks: list[str] = []
    try:
        for page_index, page in enumerate(reader.pages):
            # ``extract_text`` can raise on malformed pages; we fall
            # back to an empty string and let the sparse-page branch
            # kick in.
            try:
                page_text = page.extract_text() or ""
            except Exception:  # noqa: BLE001 — PDF extraction is noisy
                page_text = ""

            page_text = page_text.rstrip()

            if (
                pdfplumber_available
                and len(page_text) < _SPARSE_CHAR_THRESHOLD
            ):
                if plumber_doc is None:
                    plumber_doc = pdfplumber.open(str(pdf_path))
                markdown_tables = _extract_tables_as_markdown(
                    plumber_doc, page_index,
                )
                if markdown_tables:
                    # Keep whatever ``pypdf`` did extract — even sparse
                    # text can carry page numbers, titles, etc. — then
                    # append the Markdown tables separated by blank
                    # lines.
                    if page_text:
                        page_text = (
                            page_text + _PAGE_SEPARATOR + markdown_tables
                        )
                    else:
                        page_text = markdown_tables

            page_blocks.append(page_text)
    finally:
        if plumber_doc is not None:
            plumber_doc.close()

    # Drop trailing blank pages so the document doesn't end with
    # gratuitous whitespace — but preserve blank pages *between* real
    # pages because they're a legitimate document-structure signal.
    while page_blocks and not page_blocks[-1].strip():
        page_blocks.pop()

    canonical_text = _PAGE_SEPARATOR.join(page_blocks)
    return canonical_text, []


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _extract_tables_as_markdown(plumber_doc: Any, page_index: int) -> str:
    """Return Markdown-table serialisations of tables on *page_index*.

    *plumber_doc* is a ``pdfplumber.PDF`` instance. Silently returns an
    empty string on any failure — table extraction is best-effort and
    must never take down an ingestion run.
    """
    try:
        if page_index >= len(plumber_doc.pages):
            return ""
        page = plumber_doc.pages[page_index]
        tables = page.extract_tables() or []
    except Exception:  # noqa: BLE001 — pdfplumber internals are fragile
        return ""

    if not tables:
        return ""

    rendered_blocks: list[str] = []
    for table in tables:
        # A table is a list of rows; each row is a list of cells
        # (possibly ``None``). Skip empty tables and tables with a
        # ragged header (fewer than two columns) because those don't
        # round-trip cleanly to Markdown.
        if not table or len(table[0]) < 2:
            continue
        rendered = _rows_to_markdown_table(table)
        if rendered:
            rendered_blocks.append(rendered)

    return _PAGE_SEPARATOR.join(rendered_blocks)


def _rows_to_markdown_table(rows: list[list[str | None]]) -> str:
    """Serialise *rows* as a GitHub-flavoured Markdown table.

    The first row is treated as the header. Cells are normalised:
    ``None`` becomes empty, pipe characters are backslash-escaped so
    they cannot break the table grammar, and embedded newlines become
    single spaces (Markdown tables can't span lines).
    """
    if not rows:
        return ""

    n_cols = len(rows[0])
    if n_cols < 2:
        # Single-column tables render as lists more naturally. Skip.
        return ""

    def _cell(value: str | None) -> str:
        if value is None:
            return ""
        # Collapse any whitespace (including newlines) to single spaces
        # and escape pipes.
        collapsed = " ".join(str(value).split())
        return collapsed.replace("|", "\\|")

    header_cells = [_cell(c) for c in rows[0]]
    # Pad/truncate rows to match the header width so the Markdown table
    # is syntactically well-formed.
    body_rows: list[list[str]] = []
    for row in rows[1:]:
        padded = list(row) + [None] * max(0, n_cols - len(row))
        padded = padded[:n_cols]
        body_rows.append([_cell(c) for c in padded])

    separator = "|".join(["---"] * n_cols)
    lines = [
        "| " + " | ".join(header_cells) + " |",
        "|" + separator + "|",
    ]
    for body_row in body_rows:
        lines.append("| " + " | ".join(body_row) + " |")
    return "\n".join(lines)


__all__ = ["parse_pdf"]
