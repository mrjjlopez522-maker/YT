-- Shorts Studio schema (SQLite). Columns ending in _json hold JSON text.
-- Foreign keys are enforced (PRAGMA foreign_keys = ON in database.py).

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id          TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    niche               TEXT,
    youtube_channel_id  TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topics (
    topic_id         TEXT PRIMARY KEY,
    channel_id       TEXT NOT NULL REFERENCES channels(channel_id),
    topic            TEXT NOT NULL,
    slug             TEXT NOT NULL,
    category         TEXT,
    trend_signal     REAL,              -- NULL = no measured signal (never invented)
    trend_source     TEXT,              -- provider that produced the signal
    trend_evidence_json TEXT,
    date_detected    TEXT NOT NULL,
    source_count     INTEGER NOT NULL DEFAULT 0,
    potential_angle  TEXT,
    evergreen_score  REAL,
    timeliness       TEXT,              -- breaking | rising | seasonal | recurring | evergreen | unknown
    research_status  TEXT NOT NULL DEFAULT 'NEW',  -- NEW | RESEARCHING | RESEARCHED | INSUFFICIENT | FAILED
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (channel_id, slug)
);

CREATE TABLE IF NOT EXISTS research (
    research_id    TEXT PRIMARY KEY,
    topic_id       TEXT NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    provider       TEXT NOT NULL,
    title          TEXT NOT NULL,
    url            TEXT,
    retrieved_at   TEXT NOT NULL,
    content_path   TEXT,               -- local snapshot of what was read
    content_hash   TEXT,
    text_license   TEXT,               -- e.g. CC-BY-SA-4.0 for Wikipedia prose: evidence only, never copied
    reliability    TEXT NOT NULL,      -- primary | secondary | tertiary | user_notes
    summary        TEXT
);

CREATE TABLE IF NOT EXISTS research_facts (
    fact_id        TEXT PRIMARY KEY,
    research_id    TEXT NOT NULL REFERENCES research(research_id) ON DELETE CASCADE,
    topic_id       TEXT NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    local_key      TEXT,               -- id used in notes files (e.g. f3)
    position       INTEGER NOT NULL DEFAULT 0,  -- authored order within the provider
    text           TEXT NOT NULL,      -- the fact, in our own words when own_words = 1
    own_words      INTEGER NOT NULL DEFAULT 0,
    source_title   TEXT,
    source_url     TEXT,
    extra_sources_json TEXT,           -- additional corroborating citations
    tags_json      TEXT,
    fact_date      TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    source_id        TEXT PRIMARY KEY,
    topic_id         TEXT REFERENCES topics(topic_id) ON DELETE SET NULL,
    source_url       TEXT NOT NULL UNIQUE,
    platform         TEXT NOT NULL,
    creator          TEXT,
    title            TEXT,
    date_found       TEXT NOT NULL,
    media_type       TEXT NOT NULL,     -- video | image | audio
    role             TEXT NOT NULL DEFAULT 'visual',  -- visual | music | sfx | ambience
    download_url     TEXT,
    local_path       TEXT,
    content_hash     TEXT,
    duration         REAL,
    width            INTEGER,
    height           INTEGER,
    fps              REAL,
    has_audio        INTEGER,
    description      TEXT,
    tags_json        TEXT,
    source_timestamps_json TEXT,        -- useful [start, end, note] ranges
    analysis_json    TEXT,              -- source intelligence output
    status           TEXT NOT NULL DEFAULT 'DISCOVERED',  -- DISCOVERED | APPROVED | REJECTED | INGESTED
    rejection_reason TEXT,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS licenses (
    license_id              TEXT PRIMARY KEY,
    source_id               TEXT NOT NULL UNIQUE REFERENCES sources(source_id) ON DELETE CASCADE,
    license_type            TEXT NOT NULL,      -- normalised id, e.g. CC-BY-4.0, PD-USGov, UNKNOWN
    license_url             TEXT,
    commercial_use_allowed  INTEGER NOT NULL,
    modification_allowed    INTEGER NOT NULL,
    attribution_required    INTEGER NOT NULL,
    share_alike             INTEGER NOT NULL DEFAULT 0,
    audio_reuse_allowed     INTEGER NOT NULL DEFAULT 0,
    attribution_text        TEXT,
    permission_reference    TEXT,
    permission_date         TEXT,
    permission_notes        TEXT,
    evidence_json           TEXT,               -- raw license metadata as retrieved
    evidence_path           TEXT,               -- licenses/<source_id>.json snapshot
    rights_confidence       REAL NOT NULL,
    verification_status     TEXT NOT NULL,      -- VERIFIED | REJECTED
    verified_by             TEXT NOT NULL,      -- auto | human:<name>
    reasons_json            TEXT,
    verified_at             TEXT NOT NULL
);

-- The rights record exactly as specified, one row per source.
CREATE VIEW IF NOT EXISTS source_rights AS
SELECT s.source_id, s.source_url, s.platform, s.creator, s.title, s.date_found,
       l.license_type, l.commercial_use_allowed, l.modification_allowed, l.attribution_required,
       l.permission_reference, l.permission_date, l.permission_notes,
       s.source_timestamps_json AS source_timestamps, l.rights_confidence,
       l.verification_status, s.status
FROM sources s LEFT JOIN licenses l ON l.source_id = s.source_id;

CREATE TABLE IF NOT EXISTS voices (
    voice_id       TEXT PRIMARY KEY,
    provider       TEXT NOT NULL,
    voice_name     TEXT NOT NULL,
    settings_json  TEXT,
    created_at     TEXT NOT NULL,
    UNIQUE (provider, voice_name, settings_json)
);

CREATE TABLE IF NOT EXISTS scripts (
    script_id       TEXT PRIMARY KEY,
    topic_id        TEXT NOT NULL REFERENCES topics(topic_id),
    version         INTEGER NOT NULL DEFAULT 1,
    format          TEXT NOT NULL,
    angle           TEXT,
    blueprint_json  TEXT NOT NULL,
    hooks_json      TEXT NOT NULL,      -- 5 candidates with scores
    selected_hook   TEXT NOT NULL,
    sections_json   TEXT NOT NULL,      -- [{section, sentences:[{text, fact_ids}]}]
    full_text       TEXT NOT NULL,
    word_count      INTEGER NOT NULL,
    est_duration    REAL NOT NULL,
    target_duration INTEGER NOT NULL,
    llm_provider    TEXT NOT NULL,
    style_report_json TEXT,
    factcheck_status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING | PASSED | FAILED
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id     TEXT PRIMARY KEY,
    script_id    TEXT NOT NULL REFERENCES scripts(script_id) ON DELETE CASCADE,
    claim        TEXT NOT NULL,
    section      TEXT,
    fact_id      TEXT REFERENCES research_facts(fact_id),
    source       TEXT,
    source_url   TEXT,
    confidence   REAL NOT NULL,
    status       TEXT NOT NULL,       -- VERIFIED | NEEDS_REVIEW | UNVERIFIED | REJECTED
    notes        TEXT,
    reviewed_by  TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    video_id          TEXT PRIMARY KEY,   -- equals base_name
    channel_id        TEXT NOT NULL REFERENCES channels(channel_id),
    topic_id          TEXT NOT NULL REFERENCES topics(topic_id),
    script_id         TEXT REFERENCES scripts(script_id),
    voice_id          TEXT REFERENCES voices(voice_id),
    base_name         TEXT NOT NULL UNIQUE,
    seq               INTEGER NOT NULL,
    status            TEXT NOT NULL,
    failed_stage      TEXT,
    render_path       TEXT,
    duration          REAL,
    width             INTEGER,
    height            INTEGER,
    fps               REAL,
    metadata_json     TEXT,               -- titles/descriptions/keywords/hashtags/thumbnail concepts
    selected_title    TEXT,
    selected_description TEXT,
    tags_json         TEXT,
    qc_status         TEXT,               -- PASSED | FAILED
    qc_report_json    TEXT,
    risk_flags_json   TEXT,
    experiment_vars_json TEXT,            -- hook style, caption style, length... for the learning loop
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenes (
    scene_id        TEXT PRIMARY KEY,
    video_id        TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    idx             INTEGER NOT NULL,
    section         TEXT NOT NULL,
    start_time      REAL NOT NULL,
    end_time        REAL NOT NULL,
    visual_source   TEXT REFERENCES sources(source_id),   -- NULL for original graphics
    source_in       REAL,
    source_out      REAL,
    visual_type     TEXT NOT NULL,        -- footage | still | graphic
    effect          TEXT,
    narration       TEXT,
    caption         TEXT,
    transition      TEXT,
    sound_effect    TEXT,
    graphics_json   TEXT,
    UNIQUE (video_id, idx)
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id    TEXT PRIMARY KEY,
    video_id    TEXT REFERENCES videos(video_id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,   -- voice | music | sfx | ambience | mix | captions_ass | captions_srt | graphic | scene_clip | render | thumbnail | review_page
    path        TEXT NOT NULL,
    source_id   TEXT REFERENCES sources(source_id),
    voice_id    TEXT REFERENCES voices(voice_id),
    sha256      TEXT,
    duration    REAL,
    meta_json   TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id    TEXT PRIMARY KEY,
    video_id       TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    decision       TEXT NOT NULL,     -- APPROVE | REJECT | EDIT | RENDER_AGAIN | SCHEDULE
    reviewer       TEXT NOT NULL,
    allow_public   INTEGER NOT NULL DEFAULT 0,
    scheduled_for  TEXT,
    notes          TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS uploads (
    upload_id         TEXT PRIMARY KEY,
    video_id          TEXT NOT NULL REFERENCES videos(video_id),
    approval_id       TEXT REFERENCES approvals(approval_id),
    platform          TEXT NOT NULL DEFAULT 'youtube',
    youtube_video_id  TEXT,
    privacy_status    TEXT NOT NULL,
    publish_at        TEXT,
    playlist_id       TEXT,
    dry_run           INTEGER NOT NULL,
    request_json      TEXT NOT NULL,
    response_json     TEXT,
    status            TEXT NOT NULL,   -- DRY_RUN | UPLOADED | FAILED
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics (
    snapshot_id          TEXT PRIMARY KEY,
    video_id             TEXT REFERENCES videos(video_id),
    youtube_video_id     TEXT,
    captured_at          TEXT NOT NULL,
    period_start         TEXT,
    period_end           TEXT,
    views                INTEGER,
    engaged_views        INTEGER,
    likes                INTEGER,
    comments             INTEGER,
    shares               INTEGER,
    subscribers_gained   INTEGER,
    subscribers_lost     INTEGER,
    avg_view_duration    REAL,
    avg_view_percentage  REAL,
    estimated_revenue    REAL,             -- only from YouTube's monetary reports
    retention_json       TEXT,
    traffic_sources_json TEXT,
    source               TEXT NOT NULL      -- api | csv | manual
);

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id    TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    variable         TEXT NOT NULL,   -- HOOK | VIDEO_LENGTH | TITLE | TOPIC | NARRATION_STYLE | CAPTION_STYLE | EDITING_STYLE | POSTING_TIME
    variants_json    TEXT NOT NULL,
    hypothesis       TEXT,
    metric           TEXT NOT NULL DEFAULT 'views',
    min_sample_size  INTEGER NOT NULL,
    status           TEXT NOT NULL,   -- RUNNING | CONCLUDED | ABANDONED
    result_json      TEXT,
    sample_size      INTEGER,
    date_range       TEXT,
    created_at       TEXT NOT NULL,
    concluded_at     TEXT
);

CREATE TABLE IF NOT EXISTS experiment_assignments (
    experiment_id  TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    video_id       TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    variant        TEXT NOT NULL,
    PRIMARY KEY (experiment_id, video_id)
);

CREATE TABLE IF NOT EXISTS costs (
    cost_id        TEXT PRIMARY KEY,
    video_id       TEXT REFERENCES videos(video_id) ON DELETE SET NULL,
    topic_id       TEXT REFERENCES topics(topic_id) ON DELETE SET NULL,
    category       TEXT NOT NULL,   -- research | llm | tts | storage | rendering | sources | other
    provider       TEXT NOT NULL,
    units          REAL NOT NULL,
    unit_type      TEXT NOT NULL,
    estimated_usd  REAL NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS revenue (
    revenue_id    TEXT PRIMARY KEY,
    video_id      TEXT REFERENCES videos(video_id) ON DELETE SET NULL,
    period_start  TEXT NOT NULL,
    period_end    TEXT NOT NULL,
    category      TEXT NOT NULL,   -- shorts_ads | longform_ads | sponsorship | affiliate | product | fan_funding | other
    amount_usd    REAL NOT NULL,
    notes         TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS niche_metrics (
    report_id   TEXT NOT NULL,
    niche       TEXT NOT NULL,
    factor      TEXT NOT NULL,
    value       REAL,
    unit        TEXT,
    label       TEXT NOT NULL,     -- FACT | ESTIMATE | ASSUMPTION | UNKNOWN
    method      TEXT NOT NULL,
    evidence    TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (report_id, niche, factor)
);

CREATE TABLE IF NOT EXISTS errors (
    error_id     TEXT PRIMARY KEY,
    stage        TEXT NOT NULL,
    video_id     TEXT,
    topic_id     TEXT,
    error_type   TEXT NOT NULL,
    message      TEXT NOT NULL,
    traceback    TEXT,
    resolved     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS status_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    from_status  TEXT,
    to_status    TEXT NOT NULL,
    reason       TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_topic ON videos(topic_id);
CREATE INDEX IF NOT EXISTS idx_sources_topic ON sources(topic_id);
CREATE INDEX IF NOT EXISTS idx_facts_topic ON research_facts(topic_id);
CREATE INDEX IF NOT EXISTS idx_claims_script ON claims(script_id);
CREATE INDEX IF NOT EXISTS idx_scenes_video ON scenes(video_id);
CREATE INDEX IF NOT EXISTS idx_analytics_video ON analytics(video_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_costs_video ON costs(video_id);
