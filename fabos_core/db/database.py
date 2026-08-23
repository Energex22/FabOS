from pathlib import Path
import sqlite3
from contextlib import contextmanager
class Database:
    def __init__(self,path): self.path=Path(path)
    def initialize(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        sql=Path(__file__).with_name('schema.sql').read_text(encoding='utf-8')
        with self.connect() as c: c.executescript(sql); c.commit()
    @contextmanager
    def connect(self):
        c=sqlite3.connect(str(self.path),timeout=30); c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA journal_mode=WAL')
        try: yield c
        finally: c.close()
