-- Analysis layer: industry benchmarks + operating analysis results
-- Depends on: schema_base.sql (reports, text_chunks, financial_facts)

CREATE TABLE IF NOT EXISTS industry_benchmarks (
    industry      VARCHAR(128) NOT NULL,
    item_name     VARCHAR(256) NOT NULL,
    period_label  VARCHAR(32)  NOT NULL,
    p25           NUMERIC(24, 4),
    p50           NUMERIC(24, 4),
    p75           NUMERIC(24, 4),
    source        VARCHAR(32)  NOT NULL,
    meta          JSONB        DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ  DEFAULT NOW(),
    PRIMARY KEY (industry, item_name, period_label, source)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id              BIGSERIAL PRIMARY KEY,
    report_id       BIGINT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    run_type        VARCHAR(32) NOT NULL DEFAULT 'operating',
    config_version  VARCHAR(32),
    summary         TEXT,
    stats           JSONB DEFAULT '{}'::jsonb,
    benchmark_source VARCHAR(32),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_report_created
    ON analysis_runs (report_id, created_at DESC);

CREATE TABLE IF NOT EXISTS metric_flags (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    rule_id         VARCHAR(64) NOT NULL,
    severity        VARCHAR(16) NOT NULL,
    category        VARCHAR(32) NOT NULL DEFAULT 'other',
    item_name       VARCHAR(256) NOT NULL,
    period_label    VARCHAR(32),
    metric_value    NUMERIC(24, 4),
    benchmark_value NUMERIC(24, 4),
    delta           NUMERIC(24, 4),
    direction       VARCHAR(16),
    summary         TEXT NOT NULL,
    confidence      REAL,
    evidence        JSONB DEFAULT '{}'::jsonb,
    UNIQUE (run_id, rule_id, item_name, period_label)
);

CREATE INDEX IF NOT EXISTS idx_metric_flags_run ON metric_flags (run_id);

CREATE TABLE IF NOT EXISTS flag_explanations (
    id                BIGSERIAL PRIMARY KEY,
    flag_id           BIGINT NOT NULL REFERENCES metric_flags(id) ON DELETE CASCADE,
    chunk_id          BIGINT REFERENCES text_chunks(id) ON DELETE SET NULL,
    snippet           TEXT,
    section_key       VARCHAR(64),
    page_num          INT,
    relevance_score   REAL,
    explanation_type  VARCHAR(16) NOT NULL DEFAULT 'none',
    reason            TEXT
);

CREATE INDEX IF NOT EXISTS idx_flag_explanations_flag ON flag_explanations (flag_id);

CREATE TABLE IF NOT EXISTS metric_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    item_name       VARCHAR(256) NOT NULL,
    period_label    VARCHAR(32)  NOT NULL,
    current_value   NUMERIC(24, 4),
    prior_value     NUMERIC(24, 4),
    yoy_pct         NUMERIC(10, 4),
    unit            VARCHAR(32),
    is_ratio        BOOLEAN DEFAULT FALSE,
    derived         BOOLEAN DEFAULT FALSE,
    industry_p25    NUMERIC(24, 4),
    industry_p50    NUMERIC(24, 4),
    industry_p75    NUMERIC(24, 4),
    status          VARCHAR(16) NOT NULL DEFAULT 'normal',
    UNIQUE (run_id, item_name, period_label)
);

CREATE INDEX IF NOT EXISTS idx_metric_snapshots_run ON metric_snapshots (run_id);
