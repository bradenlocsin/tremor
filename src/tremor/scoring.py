"""Score live Recommendations once their horizon has passed (ADR-0018)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pandas as pd

from tremor.config import Config
from tremor.event_study import daily_returns, event_car
from tremor.events import load_events

SCHEMA = """
CREATE TABLE IF NOT EXISTS rec_scores (
    rec_id        TEXT PRIMARY KEY,
    realized_car  REAL NOT NULL,
    hit           INTEGER NOT NULL,
    scored_at     TEXT NOT NULL
);
"""


def score_live(conn: sqlite3.Connection, prices: pd.DataFrame, cfg: Config) -> int:
    """Score every saved Recommendation whose target Event's window has reached its horizon."""
    conn.executescript(SCHEMA)
    have = {r[0] for r in conn.execute("SELECT rec_id FROM rec_scores")}
    try:
        recs = conn.execute(
            "SELECT id, event_id, asset, stance, horizon_days FROM recommendations"
            " WHERE stance IS NOT NULL"
        ).fetchall()
    except sqlite3.OperationalError:  # no recommendations table yet
        return 0
    events = {e.id: e for e in load_events(conn)}
    returns = daily_returns(prices, cfg.benchmark)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    scored = 0
    for rec_id, event_id, asset, stance, horizon in recs:
        if rec_id in have or event_id not in events:
            continue
        r = event_car(returns, events[event_id], asset, cfg.benchmark, cfg.event_study)
        if isinstance(r, str) or horizon not in r.car.index:
            continue
        car = float(r.car[horizon])
        hit = (car > 0) == (stance == "Overweight")
        conn.execute("INSERT INTO rec_scores VALUES (?, ?, ?, ?)", (rec_id, car, int(hit), now))
        scored += 1
    conn.commit()
    return scored
