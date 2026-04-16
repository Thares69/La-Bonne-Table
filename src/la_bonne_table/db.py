"""SQLite connection and schema. No ORM — raw sqlite3 by design."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "la_bonne_table.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_id      TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    category     TEXT NOT NULL,
    unit_cost    REAL NOT NULL,
    sell_price   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sales (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT NOT NULL,
    ticket_id    TEXT NOT NULL,
    item_id      TEXT NOT NULL REFERENCES items(item_id),
    quantity     INTEGER NOT NULL,
    unit_price   REAL NOT NULL,
    total        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sales_date   ON sales(date);
CREATE INDEX IF NOT EXISTS idx_sales_item   ON sales(item_id);
CREATE INDEX IF NOT EXISTS idx_sales_ticket ON sales(ticket_id);

CREATE TABLE IF NOT EXISTS stock (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT NOT NULL,
    item_id      TEXT NOT NULL REFERENCES items(item_id),
    qty_open     INTEGER NOT NULL,
    qty_received INTEGER NOT NULL,
    qty_close    INTEGER NOT NULL,
    waste        INTEGER NOT NULL,
    UNIQUE(date, item_id)
);

CREATE TABLE IF NOT EXISTS calendar (
    date    TEXT PRIMARY KEY,
    is_open INTEGER NOT NULL,
    notes   TEXT
);

CREATE TABLE IF NOT EXISTS recommendations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT NOT NULL,
    type         TEXT NOT NULL,
    priority     INTEGER NOT NULL,
    message      TEXT NOT NULL,
    metric_value REAL
);
"""


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
