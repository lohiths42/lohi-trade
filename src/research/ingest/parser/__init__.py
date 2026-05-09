"""Filings_Parser and Filings_Pretty_Printer (design §3.2).

Converts PDF, HTML, and XBRL documents into a canonical Markdown
representation plus structured metadata (`CanonicalDoc`), and provides the
inverse pretty-printer required by the round-trip property (Req 10.2,
10.3). Also hosts the management-commentary / numerical-results section
tagger (Req 10.6).
"""
