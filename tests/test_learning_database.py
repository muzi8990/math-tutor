import sqlite3
from pathlib import Path
import pytest
from math_tutor.mistakes.database import Database


def legacy_database(path):
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)')
        root = Path(__import__('math_tutor.mistakes.database', fromlist=['Database']).__file__).parent
        for p in sorted((root/'migrations').glob('*.sql')):
            version = int(p.name[:3])
            if version <= 4:
                conn.executescript(p.read_text())
                conn.execute('INSERT INTO schema_migrations VALUES(?)', (version,))
        conn.execute("INSERT INTO mistakes(id,student_id,grade,created_at,updated_at) VALUES('m','s',3,'2026-10-10','2026-10-10')")
        conn.execute("INSERT INTO assets VALUES('asset','s','m','question','key','image/png',10,'hash')")
        conn.execute("INSERT INTO analysis_jobs(id,mistake_id,content_version,next_retry_at,created_at) VALUES('job','m',1,'2026-10-10','2026-10-10')")
        conn.execute("INSERT INTO analyses VALUES('analysis','job','m',1,'{}','test','test','2026-10-10')")
        conn.execute("INSERT INTO practice_sessions(id,mistake_id,content_version,created_at) VALUES('practice','m',1,'2026-10-10')")
        conn.execute("INSERT INTO attempts(id,mistake_id,content_version,text,status,hint_count,independent,evidence,diagnoses,created_at,idempotency_key,analysis_id) VALUES('attempt','m',1,'1','correct',0,1,'e','[]','2026-10-10','key','analysis')")
        conn.execute("INSERT INTO attempt_corrections VALUES('correction','attempt','teacher','r','{}','{}','2026-10-10')")
        conn.execute("INSERT INTO review_schedules(mistake_id,next_review_at) VALUES('m','2026-10-11')")


def test_upgrade_preserves_graph_and_expands_grade(tmp_path):
    path = tmp_path/'db'
    legacy_database(path)
    db = Database(path)
    db.migrate()
    db.migrate()
    with db.connect() as conn:
        conn.execute("UPDATE mistakes SET grade=12 WHERE id='m'")
        for table in ['assets','analyses','analysis_jobs','practice_sessions','attempts','attempt_corrections','review_schedules']:
            assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 1
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='mistakes_student'").fetchone()[0] == 1
        assert conn.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 5


def test_migration_foreign_key_failure_rolls_back(tmp_path):
    path = tmp_path/'db'
    legacy_database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE assets SET mistake_id='missing'")
    with pytest.raises(RuntimeError, match='外键'):
        Database(path).migrate()
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 4
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='daily_tasks'").fetchone()[0] == 0
