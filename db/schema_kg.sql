-- ============================================================
-- RE Project - Phase 2 Knowledge Graph Schema
-- 依赖: schema_base.sql (reports, structured_tables)
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS kg_entities (
    id              BIGSERIAL PRIMARY KEY,
    report_id       BIGINT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    entity_key      VARCHAR(512) NOT NULL,
    name            VARCHAR(512) NOT NULL,
    entity_type     VARCHAR(64) NOT NULL,
    attrs           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_kg_entities_report_key UNIQUE (report_id, entity_key)
);

CREATE INDEX IF NOT EXISTS idx_kg_entities_report
    ON kg_entities(report_id);

CREATE INDEX IF NOT EXISTS idx_kg_entities_type
    ON kg_entities(report_id, entity_type);

CREATE TABLE IF NOT EXISTS kg_relations (
    id                  BIGSERIAL PRIMARY KEY,
    report_id           BIGINT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    relation_type       VARCHAR(64) NOT NULL,
    subject_entity_id   BIGINT NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    object_entity_id    BIGINT NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    attrs               JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence          REAL NOT NULL DEFAULT 1.0,
    source              VARCHAR(32) NOT NULL DEFAULT 'rule',
    source_key          VARCHAR(256) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_kg_relations_report_source_key UNIQUE (report_id, source_key)
);

CREATE INDEX IF NOT EXISTS idx_kg_relations_report
    ON kg_relations(report_id);

CREATE INDEX IF NOT EXISTS idx_kg_relations_type
    ON kg_relations(report_id, relation_type);

CREATE TABLE IF NOT EXISTS kg_relation_evidence (
    id              BIGSERIAL PRIMARY KEY,
    relation_id     BIGINT NOT NULL REFERENCES kg_relations(id) ON DELETE CASCADE,
    evidence_type   VARCHAR(32) NOT NULL,
    section_key     VARCHAR(64),
    page_num        INT,
    table_id        BIGINT REFERENCES structured_tables(id) ON DELETE SET NULL,
    snippet         TEXT,
    attrs           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kg_evidence_relation
    ON kg_relation_evidence(relation_id);

COMMIT;
