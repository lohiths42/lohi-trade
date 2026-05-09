"""Lohi-Research gateway service helpers.

Home for RLS + DB-acquisition plumbing (Task 4.3) plus the real
``ResearchService`` logic that lands in Phase 14 (Task 16.1).

Today this subpackage only exposes :mod:`rls`, the per-request
``app.user_id`` helper that every research code path must run through
before touching an RLS-protected table (design §14, Req 4.5–4.6, Req 8.5).
Later phases will add run-lifecycle, reindex, memory-management, and the
full health probe modules under this same namespace.
"""
