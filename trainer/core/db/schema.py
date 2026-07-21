SCHEMA: str = """
CREATE TABLE IF NOT EXISTS training_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL CHECK (type IN ('TRAIN','REGISTER')),
    status      TEXT NOT NULL DEFAULT 'QUEUED'
                CHECK (status IN ('QUEUED','RUNNING','DONE','FAILED')),
    datasets    TEXT,
    recipe      TEXT,
    output_name TEXT NOT NULL,
    parent_run_id INTEGER,
    log_path    TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT
);
"""
