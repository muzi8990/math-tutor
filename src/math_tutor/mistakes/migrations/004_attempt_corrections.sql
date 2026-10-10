ALTER TABLE attempts ADD COLUMN analysis_id TEXT REFERENCES analyses(id) ON DELETE SET NULL;
CREATE TABLE attempt_corrections (
 id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
 actor_id TEXT NOT NULL,reason TEXT NOT NULL,original_payload TEXT NOT NULL,corrected_payload TEXT NOT NULL,created_at TEXT NOT NULL
);
