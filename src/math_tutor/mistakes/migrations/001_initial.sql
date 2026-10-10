CREATE TABLE mistakes (
 id TEXT PRIMARY KEY, student_id TEXT NOT NULL, problem_text TEXT NOT NULL DEFAULT '',
 grade INTEGER CHECK(grade BETWEEN 1 AND 6), note TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'upload',
 analysis_status TEXT NOT NULL DEFAULT 'pending', learning_status TEXT NOT NULL DEFAULT 'new',
 content_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX mistakes_student ON mistakes(student_id,created_at,id);
CREATE TABLE assets (
 id TEXT PRIMARY KEY, student_id TEXT NOT NULL, mistake_id TEXT NOT NULL REFERENCES mistakes(id) ON DELETE CASCADE,
 purpose TEXT NOT NULL, storage_key TEXT NOT NULL UNIQUE, mime TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL
);
CREATE INDEX assets_digest ON assets(student_id,sha256);
CREATE TABLE analysis_jobs (
 id TEXT PRIMARY KEY, mistake_id TEXT NOT NULL REFERENCES mistakes(id) ON DELETE CASCADE,
 content_version INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0,
 lease_token TEXT, lease_until TEXT, next_retry_at TEXT NOT NULL, error_code TEXT, created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX active_job ON analysis_jobs(mistake_id,content_version) WHERE status IN ('pending','processing');
CREATE TABLE analyses (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE REFERENCES analysis_jobs(id) ON DELETE CASCADE,
 mistake_id TEXT NOT NULL REFERENCES mistakes(id) ON DELETE CASCADE, content_version INTEGER NOT NULL,
 payload TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE knowledge_points(id TEXT PRIMARY KEY,name TEXT NOT NULL,parent_id TEXT REFERENCES knowledge_points(id),min_grade INTEGER,max_grade INTEGER);
CREATE TABLE mistake_knowledge_points (
 analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE, local_id TEXT NOT NULL,
 knowledge_point_id TEXT REFERENCES knowledge_points(id), mapping_status TEXT NOT NULL DEFAULT 'unmapped',
 PRIMARY KEY(analysis_id,local_id)
);
CREATE TABLE practice_sessions (
 id TEXT PRIMARY KEY, mistake_id TEXT NOT NULL REFERENCES mistakes(id) ON DELETE CASCADE,
 content_version INTEGER NOT NULL,hint_count INTEGER NOT NULL DEFAULT 0, consumed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE attempts (
 id TEXT PRIMARY KEY,mistake_id TEXT NOT NULL REFERENCES mistakes(id) ON DELETE CASCADE,
 content_version INTEGER NOT NULL, text TEXT NOT NULL,asset_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
 status TEXT NOT NULL,hint_count INTEGER NOT NULL,independent INTEGER NOT NULL,evidence TEXT NOT NULL,
 diagnoses TEXT NOT NULL,provenance TEXT NOT NULL DEFAULT 'model_inferred',created_at TEXT NOT NULL,
 idempotency_key TEXT NOT NULL,UNIQUE(mistake_id,idempotency_key)
);
CREATE TABLE review_schedules (
 mistake_id TEXT PRIMARY KEY REFERENCES mistakes(id) ON DELETE CASCADE,
 stage INTEGER NOT NULL DEFAULT 0,next_review_at TEXT NOT NULL,last_review_at TEXT,
 correct_dates TEXT NOT NULL DEFAULT '[]',due_passed INTEGER NOT NULL DEFAULT 0
);
