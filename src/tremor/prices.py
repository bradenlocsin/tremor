"""Daily prices behind a swappable price-source interface (ADR-0014).

Prices are cached in SQLite. History is never refetched: an update only asks the source for
days after the last cached date.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

import pandas as pd

DEFAULT_HISTORY_START = date(2014, 1, 1)  # covers estimation windows for 2015 Events


class PriceSource(Protocol):
    name: str
    license: str  # License tag (ADR-0004): 'commercial' | 'non-commercial'

    def fetch(self, ticker: str, start: date) -> pd.Series:
        """Adjusted daily closes from `start` onward, indexed by date."""
        ...


class YFinanceSource:
    """Unofficial Yahoo Finance data. Yahoo's terms make it personal / non-commercial use."""

    name = "yfinance"
    license = "non-commercial"

    def fetch(self, ticker: str, start: date) -> pd.Series:
        import yfinance as yf

        df = yf.download(
            ticker, start=start.isoformat(), auto_adjust=True, progress=False, threads=False
        )
        if df.empty:
            return pd.Series(dtype=float, name=ticker)
        close = df["Close"]
        if isinstance(close, pd.DataFrame):  # yfinance returns MultiIndex columns
            close = close[ticker]
        close.index = pd.to_datetime(close.index).date
        return close.dropna().rename(ticker)


def last_cached_date(conn: sqlite3.Connection, ticker: str) -> date | None:
    row = conn.execute("SELECT MAX(date) FROM prices WHERE ticker = ?", (ticker,)).fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None


def update_prices(
    conn: sqlite3.Connection,
    source: PriceSource,
    tickers: list[str],
    history_start: date = DEFAULT_HISTORY_START,
) -> dict[str, int]:
    """Fetch only new days for each ticker. Returns rows added per ticker."""
    added: dict[str, int] = {}
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for ticker in tickers:
        last = last_cached_date(conn, ticker)
        start = last + timedelta(days=1) if last else history_start
        conn.commit()  # end any open transaction before the (slow) network call
        series = source.fetch(ticker, start)
        series = series[[d > last for d in series.index]] if last else series
        rows = [
            (ticker, d.isoformat(), float(v), source.name, source.license, now)
            for d, v in series.items()
        ]
        conn.executemany("INSERT OR IGNORE INTO prices VALUES (?, ?, ?, ?, ?, ?)", rows)
        first = conn.execute(
            "SELECT MIN(date) FROM prices WHERE ticker = ?", (ticker,)
        ).fetchone()[0]
        if first:
            conn.execute(
                "INSERT OR REPLACE INTO assets_meta VALUES (?, ?)", (ticker, first)
            )
        added[ticker] = len(rows)
        conn.commit()  # short write transactions: never hold the lock across a download
    return added


def load_prices(conn: sqlite3.Connection, tickers: list[str]) -> pd.DataFrame:
    """Wide DataFrame of closes: one column per ticker, indexed by trading date (Timestamp)."""
    placeholders = ",".join("?" * len(tickers))
    df = pd.read_sql_query(
        f"SELECT ticker, date, close FROM prices WHERE ticker IN ({placeholders})",
        conn,
        params=tickers,
    )
    if df.empty:
        return pd.DataFrame(columns=tickers)
    wide = df.pivot(index="date", columns="ticker", values="close")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index().reindex(columns=tickers)


def first_trade_dates(conn: sqlite3.Connection) -> dict[str, date]:
    return {
        t: date.fromisoformat(d)
        for t, d in conn.execute("SELECT ticker, first_trade_date FROM assets_meta")
    }
