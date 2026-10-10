CREATE TABLE attempt_submissions (
 id TEXT PRIMARY KEY,mistake_id TEXT NOT NULL REFERENCES mistakes(id) ON DELETE CASCADE,
 content_version INTEGER NOT NULL,idempotency_key TEXT NOT NULL,digest TEXT NOT NULL,
 practice_id TEXT REFERENCES practice_sessions(id) ON DELETE CASCADE,
 status TEXT NOT NULL,lease_token TEXT,lease_until TEXT,attempt_id TEXT REFERENCES attempts(id) ON DELETE CASCADE,
 UNIQUE(mistake_id,idempotency_key)
);
