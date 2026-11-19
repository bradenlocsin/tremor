"""Back-test and Track record (ADR-0018).

For every historical Episode start, recompute the Recommendation TREMOR would have made using
only information available the day before it:
  * Comparables are earlier Episode starts (select_comparables), and
  * prices are cut off before the Event's day 0, so a Comparable whose 20-day window hadn't
    finished yet is skipped ("event window not finished yet"). This blocks look-ahead.
Then score the call against the Event's realized CAR at the Recommendation's horizon.

Scores the deterministic Stance and Confidence, before any LLM downgrade, because the LLM's
past reasoning can't be replayed faithfully. The Track record page says so.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from tremor.analysis import analyze_event, episodes_for
from tremor.config import Config
from tremor.event_study import daily_returns, event_car
from tremor.events import Event
from tremor.recommend import decide

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest (
    event_id      TEXT NOT NULL,
    asset         TEXT NOT NULL,
    occurred_on   TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    stance        TEXT NOT NULL,
    horizon_days  INTEGER NOT NULL,
    confidence    TEXT NOT NULL,
    predicted_car REAL NOT NULL,
    realized_car  REAL NOT NULL,
    hit           INTEGER NOT NULL,
    n             INTEGER NOT NULL,
    PRIMARY KEY (event_id, asset)
);
"""


@dataclass(frozen=True)
class Call:
    event_id: str
    asset: str
    occurred_on: str
    event_type: str
    stance: str
    horizon_days: int
    confidence: str
    predicted_car: float
    realized_car: float
    n: int

    @property
    def hit(self) -> bool:
        return (self.realized_car > 0) == (self.stance == "Overweight")

    @property
    def signed_return(self) -> float:
        """Abnormal return earned by following the call (long if Overweight, short if Under)."""
        return self.realized_car if self.stance == "Overweight" else -self.realized_car


def prices_before(prices: pd.DataFrame, event: Event, benchmark: str) -> pd.DataFrame:
    """Prices strictly before the Event's day 0 (first trading day on/after the Event)."""
    cal = prices.index[prices[benchmark].notna()]
    pos = cal.searchsorted(pd.Timestamp(event.occurred_on))
    if pos >= len(cal):
        return prices
    return prices.loc[prices.index < cal[pos]]


def run_backtest(events: list[Event], prices: pd.DataFrame, cfg: Config) -> list[Call]:
    episodes = episodes_for(events, prices, cfg)
    fidelity = {e.id: e.fidelity for e in events}
    returns_full = daily_returns(prices, cfg.benchmark)
    calls: list[Call] = []
    for ep in episodes:
        target = ep.first
        visible = prices_before(prices, target, cfg.benchmark)
        analysis = analyze_event(target, events, visible, cfg, episodes)
        for asset, result in analysis.results.items():
            rec = decide(target, asset, result, fidelity)
            if not rec.exists:
                continue
            realized = event_car(returns_full, target, asset, cfg.benchmark, cfg.event_study)
            if isinstance(realized, str) or rec.horizon_days not in realized.car.index:
                continue  # the Event's own window hasn't finished: score it later
            calls.append(Call(
                event_id=target.id, asset=asset, occurred_on=target.occurred_on.isoformat(),
                event_type=target.event_type, stance=rec.stance, horizon_days=rec.horizon_days,
                confidence=rec.confidence_computed, predicted_car=rec.mean_car,
                realized_car=float(realized.car[rec.horizon_days]), n=rec.n,
            ))
    return calls


def save_backtest(conn: sqlite3.Connection, calls: list[Call]) -> None:
    conn.executescript(SCHEMA)
    conn.execute("DELETE FROM backtest")
    conn.executemany(
        "INSERT INTO backtest VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(c.event_id, c.asset, c.occurred_on, c.event_type, c.stance, c.horizon_days,
          c.confidence, c.predicted_car, c.realized_car, int(c.hit), c.n) for c in calls],
    )
    conn.commit()


def summarize(calls: list[Call]) -> pd.DataFrame:
    """Track record: overall and by Confidence."""
    if not calls:
        return pd.DataFrame(columns=["group", "calls", "hit_rate", "avg_signed_car",
                                     "avg_car_when_right", "avg_car_when_wrong"])
    df = pd.DataFrame([{**c.__dict__, "hit": c.hit, "signed": c.signed_return} for c in calls])

    def row(name, g):
        right, wrong = g[g.hit], g[~g.hit]
        return {
            "group": name,
            "calls": len(g),
            "hit_rate": g.hit.mean(),
            "avg_signed_car": g.signed.mean(),
            "avg_car_when_right": right.signed.mean() if len(right) else float("nan"),
            "avg_car_when_wrong": wrong.signed.mean() if len(wrong) else float("nan"),
        }

    rows = [row("all", df)]
    for level in ("High", "Med", "Low"):
        g = df[df.confidence == level]
        if len(g):
            rows.append(row(f"Confidence {level}", g))
    return pd.DataFrame(rows)
