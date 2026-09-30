-- TikTok engine tables, layered on top of studio/db/schema.sql.
-- (topics, sources, licenses, research, claims, scripts, scenes, assets, videos, experiments,
--  uploads, analytics, errors come from the core schema; extra columns are added in context.py)

CREATE TABLE IF NOT EXISTS trends (
    trend_id            TEXT PRIMARY KEY,
    topic               TEXT NOT NULL,
    category            TEXT,
    date_detected       TEXT NOT NULL,
    trend_source        TEXT NOT NULL,      -- observation | manual | wikipedia_pageviews | rss | youtube_most_popular | own_analytics
    trend_type          TEXT,               -- rising | emerging | evergreen | seasonal | cultural_moment | search | question | format | sound
    trend_signal        REAL,               -- NULL when nothing was measured (never invented)
    growth_signal       REAL,
    content_volume      REAL,
    potential_angle     TEXT,
    expiration_estimate TEXT,               -- ISO date or 'evergreen'
    evidence_json       TEXT,
    topic_id            TEXT REFERENCES topics(topic_id),
    status              TEXT NOT NULL DEFAULT 'NEW',   -- NEW | USED | EXPIRED | DISMISSED
    created_at          TEXT NOT NULL,
    UNIQUE (trend_source, topic, date_detected)
);

CREATE TABLE IF NOT EXISTS formats (
    format_id            TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    content_format       TEXT NOT NULL,     -- MINI_DOCUMENTARY | EXPLAINER | MYTH_VS_FACT | TIMELINE | ...
    hook_style           TEXT,
    target_length        INTEGER,
    cut_frequency        REAL,              -- visual changes per 10 s
    text_density         TEXT,
    narration_style      TEXT,
    visual_style         TEXT,
    story_structure_json TEXT NOT NULL,     -- [{slot, start, end, purpose}]
    comment_prompt_style TEXT,
    payoff_type          TEXT,
    cta_style            TEXT,
    why_it_works         TEXT,
    evidence_label       TEXT NOT NULL,     -- ASSUMPTION until data supports it
    stats_json           TEXT,              -- per-template performance from our own analytics
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS format_observations (
    obs_id          TEXT PRIMARY KEY,
    trend_id        TEXT REFERENCES trends(trend_id) ON DELETE SET NULL,
    format_id       TEXT REFERENCES formats(format_id) ON DELETE SET NULL,
    observed_at     TEXT NOT NULL,
    observer        TEXT,
    hook_style      TEXT,
    video_length    REAL,
    cut_frequency   REAL,
    text_density    TEXT,
    narration_style TEXT,
    visual_style    TEXT,
    story_structure TEXT,
    comment_prompt  TEXT,
    payoff_type     TEXT,
    cta_style       TEXT,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS series (
    series_id            TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    description          TEXT,
    visual_identity_json TEXT,
    caption_style        TEXT,
    voice                TEXT,
    intro_style          TEXT,
    outro_style          TEXT,
    created_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brands (
    brand_id      TEXT PRIMARY KEY,
    channel_name  TEXT NOT NULL,
    config_json   TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ideas (
    idea_id                    TEXT PRIMARY KEY,
    batch_id                   TEXT NOT NULL,
    trend_id                   TEXT REFERENCES trends(trend_id) ON DELETE SET NULL,
    topic_id                   TEXT REFERENCES topics(topic_id) ON DELETE SET NULL,
    topic                      TEXT NOT NULL,
    hook                       TEXT NOT NULL,
    hook_type                  TEXT NOT NULL,
    format_id                  TEXT REFERENCES formats(format_id),
    target_length              INTEGER NOT NULL,
    audience                   TEXT,
    source_requirements_json   TEXT,
    original_angle             TEXT,
    research_requirements_json TEXT,
    visual_requirements_json   TEXT,
    mode                       TEXT NOT NULL,
    series_id                  TEXT REFERENCES series(series_id),
    signals_json               TEXT,
    status                     TEXT NOT NULL DEFAULT 'NEW',  -- NEW | SHORTLISTED | ELIMINATED | DEVELOPING | PRODUCED
    elimination_reason         TEXT,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_packets (
    packet_id        TEXT PRIMARY KEY,
    topic_id         TEXT NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    path             TEXT NOT NULL,
    facts            INTEGER NOT NULL,
    sources          INTEGER NOT NULL,
    primary_sources  INTEGER NOT NULL,
    contradictions   INTEGER NOT NULL,
    complete         INTEGER NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audio (
    audio_id         TEXT PRIMARY KEY,
    video_id         TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    track            TEXT NOT NULL,       -- VOICE | MUSIC | SFX | AMBIENCE | MIX
    path             TEXT NOT NULL,
    source_id        TEXT REFERENCES sources(source_id),
    provider         TEXT,
    duration         REAL,
    integrated_lufs  REAL,
    true_peak_db     REAL,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comment_prompts (
    prompt_id   TEXT PRIMARY KEY,
    video_id    TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    kind        TEXT,
    selected    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_exports (
    export_id      TEXT PRIMARY KEY,
    video_id       TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    platform       TEXT NOT NULL,        -- tiktok | youtube_shorts | instagram_reels | facebook_reels
    caption        TEXT,
    description    TEXT,
    hashtags_json  TEXT,
    cta            TEXT,
    path           TEXT,
    status         TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    UNIQUE (video_id, platform)
);

CREATE INDEX IF NOT EXISTS idx_trends_date ON trends(date_detected);
CREATE INDEX IF NOT EXISTS idx_ideas_batch ON ideas(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_audio_video ON audio(video_id);
