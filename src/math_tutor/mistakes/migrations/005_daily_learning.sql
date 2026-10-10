CREATE TABLE mistakes_k12 (
 id TEXT PRIMARY KEY, student_id TEXT NOT NULL, problem_text TEXT NOT NULL DEFAULT '',
 grade INTEGER CHECK(grade BETWEEN 1 AND 12), note TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'upload',
 analysis_status TEXT NOT NULL DEFAULT 'pending', learning_status TEXT NOT NULL DEFAULT 'new',
 content_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
INSERT INTO mistakes_k12 SELECT id,student_id,problem_text,grade,note,source,analysis_status,learning_status,content_version,created_at,updated_at FROM mistakes;
DROP TABLE mistakes;
ALTER TABLE mistakes_k12 RENAME TO mistakes;
CREATE INDEX mistakes_student ON mistakes(student_id,created_at,id);
CREATE TABLE learning_preferences (
 student_id TEXT PRIMARY KEY, grade INTEGER CHECK(grade BETWEEN 1 AND 12), timezone TEXT NOT NULL,
 daily_enabled INTEGER NOT NULL CHECK(daily_enabled IN (0,1)), generation_time TEXT NOT NULL,
 daily_limit INTEGER NOT NULL CHECK(daily_limit BETWEEN 1 AND 10), next_run_at TEXT, updated_at TEXT NOT NULL
);
CREATE INDEX learning_next_run ON learning_preferences(next_run_at) WHERE daily_enabled=1;
CREATE TABLE daily_tasks (
 id TEXT PRIMARY KEY, student_id TEXT NOT NULL, local_date TEXT NOT NULL, timezone TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('manual','scheduled')), policy_version TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(student_id,local_date)
);
CREATE INDEX daily_tasks_student ON daily_tasks(student_id,local_date);
CREATE TABLE daily_task_items (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES daily_tasks(id) ON DELETE CASCADE,
 mistake_id TEXT REFERENCES mistakes(id) ON DELETE SET NULL, mistake_id_snapshot TEXT NOT NULL,
 content_version INTEGER NOT NULL, reason TEXT NOT NULL, due_at TEXT,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','needs_confirmation','invalidated')),
 attempt_id TEXT REFERENCES attempts(id) ON DELETE SET NULL, outcome TEXT, independent INTEGER,
 position INTEGER NOT NULL, UNIQUE(task_id,mistake_id_snapshot)
);
CREATE INDEX daily_items_mistake ON daily_task_items(mistake_id);
ALTER TABLE practice_sessions ADD COLUMN daily_task_item_id TEXT REFERENCES daily_task_items(id) ON DELETE SET NULL;
CREATE INDEX practice_daily_item ON practice_sessions(daily_task_item_id);
