"""Versioned SQLite migrations; one connection per unit of work."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=15000')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def migrate(self):
        files = sorted((Path(__file__).parent / 'migrations').glob('*.sql'))
        with self.connect() as conn:
            # Parent-table rebuild must not cascade child records. Only this
            # migration connection disables enforcement, before beginning.
            conn.execute('PRAGMA foreign_keys=OFF')
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY)')
            versions = {row[0] for row in conn.execute('SELECT version FROM schema_migrations')}
            known = {int(path.name.split('_')[0]) for path in files}
            if versions - known:
                raise RuntimeError('数据库版本高于当前服务支持的版本。')
            for path in files:
                version = int(path.name.split('_')[0])
                if version not in versions:
                    # executescript implicitly commits; execute each complete SQL
                    # statement inside our existing migration lock instead.
                    statement = ''
                    for char in path.read_text():
                        statement += char
                        if char == ';' and sqlite3.complete_statement(statement):
                            conn.execute(statement)
                            statement = ''
                    if statement.strip():
                        raise RuntimeError('迁移 SQL 不完整。')
                    conn.execute('INSERT INTO schema_migrations(version) VALUES(?)', (version,))

            if conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise RuntimeError('数据库迁移外键检查失败。')
