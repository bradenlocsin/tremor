"""Scheduled jobs (ADR-0015) and backups (ADR-0016).

* hourly: pull new GDELT 2.0 Candidates, refine them (if credentials exist)
* daily, after the US close: prices → Recommendations for recent Episodes → back-test and
  live scoring → database backup

`run_scheduler()` is a small always-on loop for the single host. Every step is wrapped so one
failure is logged and doesn't stop the others or the loop.
"""

from __future__ import annotations

import os
import sqlite3
import time
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tremor.config import Config, load_config

DAILY_RUN_UTC_HOUR = 22  # 22:00 UTC is after the 4pm New York close all year round
BACKUPS_KEPT = 7


def log(msg: str) -> None:
    print(f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S}Z {msg}", flush=True)


def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _step(name: str, fn) -> None:
    try:
        log(f"{name}: start")
        result = fn()
        log(f"{name}: done {result if result is not None else ''}")
    except Exception:  # noqa: BLE001 - keep the scheduler alive
        log(f"{name}: FAILED\n{traceback.format_exc()}")


def hourly(cfg: Config | None = None) -> None:
    from tremor import gdelt
    from tremor.storage import connect
    from tremor.taxonomy import default_taxonomy

    cfg = cfg or load_config()
    conn = connect(cfg.storage_path)
    gdelt.ensure_schema(conn)
    tax = default_taxonomy().first_slice()
    _step("gdelt pull", lambda: gdelt.pull_latest(conn, tax))
    if has_credentials():
        from tremor.refine import ClaudeRefiner, refine_candidates

        since = (datetime.now(UTC) - timedelta(days=3)).date().isoformat()
        _step("refine", lambda: refine_candidates(
            conn, cfg, tax, ClaudeRefiner(cfg.refinement_model), since=since, log=log))
    else:
        log("refine: skipped (no Anthropic credentials)")


def daily(cfg: Config | None = None) -> None:
    from tremor.analysis import analyze_event, episodes_for
    from tremor.backtest import run_backtest, save_backtest
    from tremor.events import load_events
    from tremor.prices import YFinanceSource, load_prices, update_prices
    from tremor.recommend import ClaudeExplainer, recommend, save_recommendations
    from tremor.scoring import score_live
    from tremor.storage import connect

    cfg = cfg or load_config()
    conn = connect(cfg.storage_path)
    _step("prices", lambda: update_prices(conn, YFinanceSource(), cfg.tickers))
    prices = load_prices(conn, cfg.tickers)
    events = load_events(conn)

    def recs():
        if not cfg.recommendations_enabled:
            return "switched off"
        episodes = episodes_for(events, prices, cfg)
        cutoff = (datetime.now(UTC) - timedelta(days=30)).date()
        recent = [ep.first for ep in episodes if ep.end >= cutoff]
        explainer = ClaudeExplainer(cfg.rationale_model) if has_credentials() else None
        by_id = {e.id: e for e in events}
        for target in recent:
            save_recommendations(conn, recommend(
                analyze_event(target, events, prices, cfg, episodes), by_id, explainer, conn))
        return f"{len(recent)} recent Episodes"

    _step("recommendations", recs)
    _step("backtest", lambda: save_backtest(conn, run_backtest(events, prices, cfg)))
    _step("score live", lambda: score_live(conn, prices, cfg))
    _step("backup", lambda: backup(conn, cfg.storage_path.parent / "backups"))


def backup(conn: sqlite3.Connection, folder: Path, keep: int = BACKUPS_KEPT) -> Path:
    """Consistent online copy via SQLite's backup API; keeps the newest `keep` files."""
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"tremor-{datetime.now(UTC):%Y%m%d}.sqlite"
    with sqlite3.connect(dest) as out:
        conn.backup(out)
    for old in sorted(folder.glob("tremor-*.sqlite"))[:-keep]:
        old.unlink()
    return dest


def run_scheduler() -> None:  # pragma: no cover - long-running loop
    log("scheduler started")
    last_hour = last_day = None
    while True:
        now = datetime.now(UTC)
        if now.minute >= 5 and last_hour != (now.date(), now.hour):
            last_hour = (now.date(), now.hour)
            hourly()
        if now.hour >= DAILY_RUN_UTC_HOUR and last_day != now.date() and now.weekday() < 5:
            last_day = now.date()
            daily()
        time.sleep(60)
