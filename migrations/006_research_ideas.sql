-- Research Ideas / Themes / Sectors tables
-- Required for the proactive research scheduler (multibagg-style surface)

-- ── Ideas ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS research_ideas (
    idea_id       TEXT PRIMARY KEY,
    symbol        TEXT NOT NULL UNIQUE,
    archetype     TEXT NOT NULL DEFAULT 'unknown',
    sector        TEXT NOT NULL DEFAULT 'other',
    subsector     TEXT,
    headline      TEXT NOT NULL DEFAULT '',
    thesis_short  TEXT NOT NULL DEFAULT '',
    direction     TEXT NOT NULL DEFAULT 'neutral',
    conviction    REAL NOT NULL DEFAULT 0.0,
    conviction_band TEXT NOT NULL DEFAULT 'speculative',
    tags          JSONB NOT NULL DEFAULT '[]'::jsonb,
    key_citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_run_id TEXT,
    brief_preview TEXT,
    created_at    TEXT NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
    updated_at    TEXT NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
);

CREATE INDEX IF NOT EXISTS idx_research_ideas_sector ON research_ideas(sector);
CREATE INDEX IF NOT EXISTS idx_research_ideas_archetype ON research_ideas(archetype);
CREATE INDEX IF NOT EXISTS idx_research_ideas_conviction ON research_ideas(conviction DESC);

-- ── Themes ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS research_themes (
    theme_id    TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT 'custom',
    sector      TEXT,
    summary     TEXT NOT NULL DEFAULT '',
    report_md   TEXT NOT NULL DEFAULT '',
    archetypes  JSONB NOT NULL DEFAULT '[]'::jsonb,
    members     JSONB NOT NULL DEFAULT '[]'::jsonb,
    citations   JSONB NOT NULL DEFAULT '[]'::jsonb,
    hero_url    TEXT,
    created_at  TEXT NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
    updated_at  TEXT NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
);

CREATE INDEX IF NOT EXISTS idx_research_themes_kind ON research_themes(kind);
CREATE INDEX IF NOT EXISTS idx_research_themes_sector ON research_themes(sector);

-- ── Sector Clusters ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS research_sector_clusters (
    sector      TEXT PRIMARY KEY,
    members     JSONB NOT NULL DEFAULT '[]'::jsonb,
    bias        REAL NOT NULL DEFAULT 0.0,
    theme_id    TEXT,
    headline    TEXT,
    updated_at  TEXT NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
);

-- ── Signals ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS research_signals (
    signal_id       TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    direction       TEXT NOT NULL DEFAULT 'neutral',
    conviction      REAL NOT NULL DEFAULT 0.0,
    archetype       TEXT NOT NULL DEFAULT 'unknown',
    sector          TEXT,
    source_run_id   TEXT NOT NULL DEFAULT '',
    thesis_short    TEXT NOT NULL DEFAULT '',
    emitted_at      REAL NOT NULL DEFAULT 0.0,
    expires_at      REAL NOT NULL DEFAULT 0.0,
    consumed_by_algo BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_research_signals_symbol ON research_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_research_signals_emitted ON research_signals(emitted_at DESC);
