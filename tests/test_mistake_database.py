import sqlite3
from uuid import uuid4

import pytest
from math_tutor.mistakes.database import Database
from math_tutor.settings import Settings


def test_migrate_restart_and_foreign_keys(tmp_path):
    path = tmp_path / 'db.sqlite3'
    db = Database(path)
    db.migrate()
    with db.connect() as conn:
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        conn.execute("INSERT INTO mistakes(id,student_id,created_at,updated_at) VALUES(?,?,?,?)", (str(uuid4()), str(uuid4()), '2026-10-09T00:00:00+00:00', '2026-10-09T00:00:00+00:00'))
    Database(path).migrate()
    with Database(path).connect() as conn:
        assert conn.execute('SELECT count(*) FROM mistakes').fetchone()[0] == 1
        conn.execute('INSERT INTO schema_migrations(version) VALUES(999)')
    with pytest.raises(RuntimeError):
        db.migrate()


def test_config_defaults_and_invalid_values():
    settings = Settings(_env_file=None)
    assert not settings.enable_local_identity
    assert settings.local_student_id is None
    assert settings.review_intervals == [1, 3, 7]
    for kwargs in ({'student_timezone': 'missing/timezone'}, {'review_intervals': [3, 1]}, {'review_intervals': [0]}):
        with pytest.raises(ValueError):
            Settings(_env_file=None, **kwargs)


@pytest.mark.parametrize('intervals', [[True,3,7],[1.0,3,7]])
def test_intervals_are_strict_integers(intervals):
    with pytest.raises(ValueError):
        Settings(_env_file=None,review_intervals=intervals)
