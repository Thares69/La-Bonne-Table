from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from la_bonne_table.db import init_schema


@pytest.fixture
def tmp_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "test.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    yield conn
    conn.close()
