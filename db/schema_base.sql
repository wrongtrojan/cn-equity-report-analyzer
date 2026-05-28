-- ============================================================
-- RE Project - Phase 1 Schema
-- 目标：PDF 解析结果入库 + 向量索引
-- 范围：不含 kg_entities / kg_relations（Phase 2 再做）
-- ============================================================

BEGIN;

-- ============================================================
-- PART 0: 扩展与公共函数
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector 向量检索
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- 标题/文本模糊匹配

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- PART 1: 公司与报告主数据
-- ============================================================

CREATE TABLE IF NOT EXISTS companies (
    id              BIGSERIAL PRIMARY KEY,
    stock_code      VARCHAR(16) NOT NULL,          -- 300059
    stock_name      VARCHAR(256) NOT NULL,         -- 东方财富信息股份有限公司
    exchange        VARCHAR(16),                   -- SSE / SZSE / BSE
    industry        VARCHAR(128),
    attrs           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_companies_stock_code UNIQUE (stock_code)
);

CREATE TRIGGER trg_companies_updated_at
BEFORE UPDATE ON companies
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS reports (
    id              BIGSERIAL PRIMARY KEY,
    company_id      BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    report_year     INT NOT NULL CHECK (report_year BETWEEN 1990 AND 2100),
    report_type     VARCHAR(32) NOT NULL DEFAULT 'annual',   -- annual/interim/q1/q3
    title           VARCHAR(512),
    pdf_path        TEXT NOT NULL,
    pdf_sha256      CHAR(64) NOT NULL,             -- 文件指纹，幂等去重
    pdf_size_bytes  BIGINT,
    page_count      INT,
    parse_status    VARCHAR(32) NOT NULL DEFAULT 'pending'
                    CHECK (parse_status IN ('pending','parsing','parsed','failed')),
    parse_error     TEXT,
    parsed_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_reports UNIQUE (company_id, report_year, report_type),
    CONSTRAINT uq_reports_pdf_sha256 UNIQUE (pdf_sha256)
);

CREATE INDEX IF NOT EXISTS idx_reports_company_year
    ON reports(company_id, report_year DESC);

CREATE TRIGGER trg_reports_updated_at
BEFORE UPDATE ON reports
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- PART 2: 解析产物与任务日志
-- ============================================================

CREATE TABLE IF NOT EXISTS parsed_artifacts (
    id                  BIGSERIAL PRIMARY KEY,
    report_id           BIGINT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    middle_json_path    TEXT NOT NULL,
    markdown_path       TEXT NOT NULL,
    images_dir          TEXT,
    mineru_version      VARCHAR(64),
    parse_backend       VARCHAR(32) DEFAULT 'pipeline',
    parse_lang          VARCHAR(16) DEFAULT 'ch',
    meta_json           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_parsed_artifacts_report UNIQUE (report_id)
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id              BIGSERIAL PRIMARY KEY,
    report_id       BIGINT REFERENCES reports(id) ON DELETE SET NULL,
    job_type        VARCHAR(32) NOT NULL,      -- parse/load_sections/load_tables/load_chunks/embed
    status          VARCHAR(16) NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running','success','failed')),
    input_ref       TEXT,
    output_ref      TEXT,
    error_message   TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ingest_jobs_report
    ON ingest_jobs(report_id, started_at DESC);

-- ============================================================
-- PART 3: 章节结构（按 markdown 标题切段）
-- ============================================================

CREATE TABLE IF NOT EXISTS report_sections (
    id              BIGSERIAL PRIMARY KEY,
    report_id       BIGINT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    section_key     VARCHAR(64),               -- 标准化章节键，可为空
    title_raw       TEXT NOT NULL,             -- 原始标题，如“管理层讨论与分析”
    heading_level   SMALLINT,                  -- 1=#, 2=##, 3=###
    page_start      INT,
    page_end        INT,
    content_md      TEXT,                      -- 该章节 markdown 正文
    content_text    TEXT,                      -- 去 markdown 的纯文本（可选）
    seq_no          INT NOT NULL,              -- 章节顺序
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_report_section_seq UNIQUE (report_id, seq_no)
);

CREATE INDEX IF NOT EXISTS idx_report_sections_report_key
    ON report_sections(report_id, section_key);

CREATE INDEX IF NOT EXISTS idx_report_sections_title_trgm
    ON report_sections USING gin (title_raw gin_trgm_ops);

CREATE TABLE IF NOT EXISTS section_aliases (
    id              BIGSERIAL PRIMARY KEY,
    alias_pattern   TEXT NOT NULL,             -- 正则/关键词
    section_key     VARCHAR(64) NOT NULL,
    priority        INT NOT NULL DEFAULT 100,  -- 越小优先级越高
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    note            TEXT
);

CREATE INDEX IF NOT EXISTS idx_section_aliases_key
    ON section_aliases(section_key);

-- ============================================================
-- PART 4: 通用表格存储（核心）
-- PDF 里每一个表格 -> 这里一行，不是一张 PG 表
-- ============================================================

CREATE TABLE IF NOT EXISTS structured_tables (
    id              BIGSERIAL PRIMARY KEY,
    report_id       BIGINT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    section_id      BIGINT REFERENCES report_sections(id) ON DELETE SET NULL,
    section_key     VARCHAR(64),
    table_seq       INT NOT NULL,              -- 该报告第几个表（1,2,3...）
    table_title     TEXT,                      -- 邻近标题，如“主要会计数据和财务指标”
    page_num        INT,
    row_count       INT,
    col_count       INT,
    headers         JSONB NOT NULL,            -- ["列1","列2",...]
    rows            JSONB NOT NULL,            -- [["v11","v12"],...]
    html_raw        TEXT,                      -- 原始 html table（可选）
    header_hash     CHAR(64),                  -- headers 哈希，便于归类
    table_type_guess VARCHAR(64),              -- 猜测类型（Phase1可空，Phase2用）
    source          VARCHAR(32) NOT NULL DEFAULT 'mineru',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_structured_table UNIQUE (report_id, table_seq)
);

CREATE INDEX IF NOT EXISTS idx_structured_tables_report
    ON structured_tables(report_id);

CREATE INDEX IF NOT EXISTS idx_structured_tables_section_key
    ON structured_tables(report_id, section_key);

CREATE INDEX IF NOT EXISTS idx_structured_tables_header_hash
    ON structured_tables(header_hash);

CREATE INDEX IF NOT EXISTS idx_structured_tables_headers_gin
    ON structured_tables USING gin (headers);

CREATE TABLE IF NOT EXISTS table_type_catalog (
    table_type          VARCHAR(64) PRIMARY KEY,   -- key_financials/top10_shareholders/...
    description         TEXT,
    header_signatures   JSONB NOT NULL DEFAULT '[]'::jsonb,
    section_keys        JSONB NOT NULL DEFAULT '[]'::jsonb,
    phase               SMALLINT NOT NULL DEFAULT 1,  -- 1=仅存储, 2=可抽关系
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- PART 5: 标准化财务事实（从关键表格抽取）
-- ============================================================

CREATE TABLE IF NOT EXISTS financial_facts (
    id              BIGSERIAL PRIMARY KEY,
    report_id       BIGINT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    table_id        BIGINT REFERENCES structured_tables(id) ON DELETE SET NULL,
    stmt_type       VARCHAR(32) NOT NULL,      -- income/balance/cashflow/kpi/other
    item_name       VARCHAR(256) NOT NULL,     -- 营业总收入、净利润...
    item_code       VARCHAR(64),
    period_label    VARCHAR(32) NOT NULL,      -- 2025 / 2024 / 2025Q1 / 2025年末
    period_kind     VARCHAR(16) NOT NULL DEFAULT 'year'
                    CHECK (period_kind IN ('year','quarter','point_in_time','other')),
    amount          NUMERIC(24,4),
    unit            VARCHAR(16) DEFAULT '元',
    is_ratio        BOOLEAN NOT NULL DEFAULT FALSE,
    page_num        INT,
    source_row_idx  INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_financial_fact UNIQUE (report_id, stmt_type, item_name, period_label)
);

CREATE INDEX IF NOT EXISTS idx_financial_facts_report_stmt
    ON financial_facts(report_id, stmt_type);

CREATE INDEX IF NOT EXISTS idx_financial_facts_item
    ON financial_facts(item_name);

-- ============================================================
-- PART 6: 文本切块 + pgvector
-- ============================================================

CREATE TABLE IF NOT EXISTS text_chunks (
    id              BIGSERIAL PRIMARY KEY,
    report_id       BIGINT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    section_id      BIGINT REFERENCES report_sections(id) ON DELETE SET NULL,
    section_key     VARCHAR(64),
    page_num        INT,
    chunk_index     INT NOT NULL,
    content         TEXT NOT NULL,
    token_count     INT,
    content_hash    CHAR(64),
    embedding       VECTOR(1024),              -- 按 embedding 模型维度调整
    embedding_model VARCHAR(128),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_text_chunk UNIQUE (report_id, section_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_text_chunks_report_section
    ON text_chunks(report_id, section_key);

CREATE INDEX IF NOT EXISTS idx_text_chunks_report_section_id
    ON text_chunks(report_id, section_id);

CREATE INDEX IF NOT EXISTS idx_text_chunks_content_hash
    ON text_chunks(content_hash);

-- 数据量较大后再建（181页全文建议入库完成后再建）
-- CREATE INDEX IF NOT EXISTS idx_text_chunks_embedding_hnsw
--     ON text_chunks USING hnsw (embedding vector_cosine_ops);

-- ============================================================
-- PART 7: 初始字典数据（可后续增补）
-- ============================================================

INSERT INTO section_aliases (alias_pattern, section_key, priority, note) VALUES
('^释义$', 'glossary', 10, '释义章节'),
('第[一二三四五六七八九十百\\d]+节.*重要提示', 'glossary', 12, '第一节'),
('公司简介和主要财务指标', 'company_profile', 15, '第二节'),
('^五、主要会计数据和财务指标$', 'key_financials', 10, '关键财务指标'),
('分季度主要财务指标', 'quarterly_financials', 18, '季度指标'),
('近两年的主要会计数据和财务指标', 'bond_financials', 12, '债券章节指标'),
('管理层讨论与分析', 'mda', 15, 'MD&A'),
('第[一二三四五六七八九十百\\d]+节.*公司治理', 'corporate_governance', 15, '第四节'),
('第[一二三四五六七八九十百\\d]+节.*重要事项', 'significant_matters', 15, '第五节'),
('股份变动及股东情况', 'shareholder_section', 18, '股东章节'),
('前.?10.*股东|前十名股东', 'top10_shareholders', 18, '前十大股东'),
('第[一二三四五六七八九十百\\d]+节.*债券', 'bond_section', 15, '第七节'),
('第[一二三四五六七八九十百\\d]+节.*财务报告', 'financial_statements', 12, '第八节'),
('董事.*监事.*高级管理人员|^六、董事', 'directors_supervisors', 18, '董监高'),
('主要控股参股公司|控股子公司|主要子公司', 'subsidiaries', 18, '子公司'),
('关联方|关联交易|重大关联交易', 'related_parties', 18, '关联方')
ON CONFLICT DO NOTHING;

INSERT INTO table_type_catalog (table_type, description, header_signatures, section_keys, phase) VALUES
('company_profile_kv', '公司基本信息键值表', '["股票简称","股票代码"]', '["company_profile"]', 1),
('key_financials_summary', '主要会计数据和财务指标', '["营业总收入","净利润","经营活动产生的现金流量净额"]', '["key_financials"]', 1),
('quarterly_financials', '分季度财务指标', '["第一季度","第二季度","第三季度","第四季度"]', '["quarterly_financials"]', 1),
('bond_financials', '债券章节财务指标', '["流动比率","资产负债率"]', '["bond_financials","bond_section"]', 1),
('balance_sheet', '合并资产负债表', '["期末余额","期初余额","资产总计"]', '["financial_statements"]', 1),
('income_statement', '合并利润表', '["本期发生额","营业总收入"]', '["financial_statements"]', 1),
('cashflow_statement', '合并现金流量表', '["经营活动产生的现金流量净额"]', '["financial_statements"]', 1),
('glossary_terms', '释义项-释义内容', '["释义项","释义内容"]', '["glossary"]', 2),
('top10_shareholders', '前十大股东', '["股东名称","持股比例"]', '["top10_shareholders","shareholder_section"]', 2),
('subsidiaries', '控股子公司', '["子公司名称","持股比例"]', '["subsidiaries"]', 2),
('related_party_transactions', '关联交易', '["关联方","关联交易内容","关联交易金额"]', '["related_parties","significant_matters"]', 2)
ON CONFLICT (table_type) DO NOTHING;

COMMIT;