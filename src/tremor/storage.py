"""SQLite storage. One file, WAL mode, so jobs can write while the dashboard reads."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,          -- ISO trading date
    close       REAL NOT NULL,          -- adjusted close
    source      TEXT NOT NULL,          -- Provenance: where the price came from
    license     TEXT NOT NULL,          -- License tag: 'commercial' | 'non-commercial'
    fetched_at  TEXT NOT NULL,          -- when TREMOR learned it
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS assets_meta (
    ticker            TEXT PRIMARY KEY,
    first_trade_date  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    region        TEXT NOT NULL,
    occurred_on   TEXT NOT NULL,        -- when it happened (ISO date)
    reported_at   TEXT,                 -- when it was first reported
    actors        TEXT,                 -- JSON list
    summary       TEXT,
    source_url    TEXT,
    source_name   TEXT,
    license       TEXT NOT NULL,
    fidelity      TEXT NOT NULL,        -- 'full' | 'lower'
    origin        TEXT NOT NULL         -- 'seed' | 'gdelt'
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn
