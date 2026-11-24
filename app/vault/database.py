from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3


class Vault:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.session() as conn:
            self._migrate(conn)
            conn.execute('CREATE TABLE IF NOT EXISTS volumes (id TEXT PRIMARY KEY, manifest TEXT NOT NULL, evidence TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS slips (id TEXT PRIMARY KEY REFERENCES volumes(id), digest TEXT NOT NULL, body TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS archives (id TEXT PRIMARY KEY REFERENCES volumes(id), '
                         'imprint TEXT NOT NULL, archived_at TEXT NOT NULL, years TEXT NOT NULL, '
                         'accounts TEXT NOT NULL, totals TEXT NOT NULL)')

    def _migrate(self, conn):
        # 旧版 volumes.evidence 为 NOT NULL；归档后在线库不再保存整份证据，需要放宽约束。
        columns = conn.execute('PRAGMA table_info(volumes)').fetchall()
        if not columns or all(column[3] == 0 for column in columns if column[1] == 'evidence'):
            return
        # SQLite 改列约束须重建表；按官方迁移流程在关闭外键的同一事务内重建全部相关表，
        # 否则 slips 的外键会指向被重命名的旧表。
        conn.execute('PRAGMA foreign_keys=OFF')
        conn.execute('ALTER TABLE volumes RENAME TO volumes_legacy')
        conn.execute('ALTER TABLE slips RENAME TO slips_legacy')
        conn.execute('CREATE TABLE volumes (id TEXT PRIMARY KEY, manifest TEXT NOT NULL, evidence TEXT)')
        conn.execute('CREATE TABLE slips (id TEXT PRIMARY KEY REFERENCES volumes(id), digest TEXT NOT NULL, body TEXT NOT NULL)')
        conn.execute('INSERT INTO volumes SELECT id, manifest, evidence FROM volumes_legacy')
        conn.execute('INSERT INTO slips SELECT id, digest, body FROM slips_legacy')
        conn.execute('DROP TABLE slips_legacy')
        conn.execute('DROP TABLE volumes_legacy')
        conn.execute('PRAGMA foreign_keys=ON')

    @contextmanager
    def session(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            with conn:
                yield conn
