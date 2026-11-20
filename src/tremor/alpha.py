"""Profit research track (ADR-0032): trade rules on discovery data, confirmed on a locked holdout.

Rules are simple and tradable: when a signal becomes known (the day GDELT first saw the article),
enter at the next trading day's open, hold `h` days, exit at the close, pay costs both ways.
Every rule evaluated is logged to `alpha_trials`, and the trial count raises the bar each rule
must clear (Deflated Sharpe ratio, Bailey and López de Prado 2014).
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
from scipy import stats

HOLDOUT_START = date(2025, 11, 20)  # ADR-0032: locked; never tune on dates from here on
DISCOVERY_START = date(2015, 1, 1)

ETF_5 = ("SPY", "BNO", "USO", "XLE", "GLD", "ITA", "UUP")
LARGE_15 = ("LMT", "RTX", "NOC")
SMALL_30 = ("FRO", "STNG", "INSW", "DHT", "TNK", "ZIM", "MATX", "DAC", "GSL", "BDRY", "BWET")
RESEARCH_TICKERS = ETF_5 + LARGE_15 + SMALL_30
COST_BP = {**{t: 5 for t in ETF_5}, **{t: 15 for t in LARGE_15}, **{t: 30 for t in SMALL_30}}

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_prices (
  ticker TEXT NOT NULL, date TEXT NOT NULL, open REAL NOT NULL, close REAL NOT NULL,
  PRIMARY KEY (ticker, date)
);
CREATE TABLE IF NOT EXISTS alpha_trials (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, rule TEXT NOT NULL,
  period TEXT NOT NULL, n INTEGER NOT NULL, mean REAL, sr REAL, t REAL, hit REAL,
  skew REAL, kurt REAL
);
"""


class HoldoutError(RuntimeError):
    pass


# ---------------------------------------------------------------- prices

def fetch_prices(conn: sqlite3.Connection, tickers: Iterable[str] = RESEARCH_TICKERS,
                 start: str = "2014-01-01") -> dict[str, int]:
    """Adjusted opens and closes from yfinance (personal, non-commercial use)."""
    import yfinance as yf

    conn.executescript(SCHEMA)
    out = {}
    for t in tickers:
        df = yf.download(t, start=start, auto_adjust=True, progress=False, threads=False)
        if df.empty:
            out[t] = 0
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df = df.xs(t, axis=1, level=1)
        df = df[["Open", "Close"]].dropna()
        df = df[(df["Open"] > 0) & (df["Close"] > 0)]
        conn.executemany("INSERT OR REPLACE INTO research_prices VALUES (?, ?, ?, ?)",
                         [(t, d.date().isoformat(), float(o), float(c))
                          for d, o, c in zip(df.index, df["Open"], df["Close"])])
        out[t] = len(df)
    conn.commit()
    return out


def load_ohlc(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    conn.executescript(SCHEMA)
    df = pd.read_sql("SELECT * FROM research_prices", conn, parse_dates=["date"])
    opens = df.pivot(index="date", columns="ticker", values="open").sort_index()
    closes = df.pivot(index="date", columns="ticker", values="close").sort_index()
    return opens, closes


# ---------------------------------------------------------------- trades

@dataclass(frozen=True)
class Rule:
    signal: str          # name of the signal set, e.g. "start:shipping_attack" or "+vessel_damaged"
    asset: str
    hold: int            # trading days, entry day included
    direction: int       # +1 long, -1 short
    hedge: bool = False  # subtract SPY's return over the same trade (beta 1)

    def name(self) -> str:
        return (f"{self.signal}|{self.asset}|{self.hold}d|{'long' if self.direction > 0 else 'short'}"
                f"{'|hedged' if self.hedge else ''}")


def trades(known_on: Iterable[date], opens: pd.DataFrame, closes: pd.DataFrame, rule: Rule,
           start: date = DISCOVERY_START, end: date = HOLDOUT_START,
           allow_holdout: bool = False) -> pd.DataFrame:
    """One trade per signal, entering at the first open strictly after the day it was known.
    Signals that arrive while a trade is open are skipped (no overlap, no pyramiding)."""
    if end > HOLDOUT_START and not allow_holdout:
        raise HoldoutError(f"dates from {HOLDOUT_START} on are the locked holdout (ADR-0032)")
    o, c = opens[rule.asset].dropna(), closes[rule.asset].dropna()
    cal = o.index.intersection(c.index)
    if rule.hedge:
        cal = cal.intersection(opens["SPY"].dropna().index)
    cost = 2 * COST_BP[rule.asset] / 1e4 + (2 * COST_BP["SPY"] / 1e4 if rule.hedge else 0)
    rows, busy_until = [], -1
    for k in sorted(set(known_on)):
        if not (start <= k < end):
            continue
        i = int(cal.searchsorted(pd.Timestamp(k), side="right"))  # first day after k
        j = i + rule.hold - 1
        if i <= busy_until or j >= len(cal) or cal[j].date() >= end:
            continue
        r = c[cal[j]] / o[cal[i]] - 1
        if rule.hedge:
            r -= closes["SPY"][cal[j]] / opens["SPY"][cal[i]] - 1
        rows.append((k, cal[i].date(), cal[j].date(), rule.direction * r - cost))
        busy_until = j
    return pd.DataFrame(rows, columns=["known_on", "entry", "exit", "ret"])


# ---------------------------------------------------------------- statistics

def summarize(rets: np.ndarray) -> dict:
    n = len(rets)
    if n < 2 or np.std(rets, ddof=1) == 0:
        return {"n": n, "mean": float(np.mean(rets)) if n else None, "sr": None, "t": None,
                "hit": float(np.mean(rets > 0)) if n else None, "skew": None, "kurt": None}
    sd = np.std(rets, ddof=1)
    sr = float(np.mean(rets) / sd)  # per trade
    return {"n": n, "mean": float(np.mean(rets)), "sr": sr, "t": sr * math.sqrt(n),
            "hit": float(np.mean(rets > 0)), "skew": float(stats.skew(rets)),
            "kurt": float(stats.kurtosis(rets, fisher=False))}


def deflated_sharpe(sr: float, n: int, skew: float, kurt: float, trial_srs: list[float]) -> float:
    """Probability the true Sharpe is above what the best of len(trial_srs) lucky tries would
    show (Bailey and López de Prado 2014). Per-trade Sharpe ratios throughout."""
    k = max(len(trial_srs), 1)
    var = float(np.var(trial_srs, ddof=1)) if k > 1 else 0.0
    g = 0.5772156649
    sr0 = math.sqrt(var) * ((1 - g) * stats.norm.ppf(1 - 1 / k)
                            + g * stats.norm.ppf(1 - 1 / (k * math.e))) if k > 1 else 0.0
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr * sr, 1e-12))
    return float(stats.norm.cdf((sr - sr0) * math.sqrt(n - 1) / denom))


def log_trial(conn: sqlite3.Connection, rule: Rule, period: str, s: dict) -> None:
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO alpha_trials (at, rule, period, n, mean, sr, t, hit, skew, kurt)"
                 " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (datetime.now(UTC).isoformat(timespec="seconds"), rule.name(), period, s["n"],
                  s["mean"], s["sr"], s["t"], s["hit"], s["skew"], s["kurt"]))


def trial_srs(conn: sqlite3.Connection) -> list[float]:
    conn.executescript(SCHEMA)
    return [r[0] for r in conn.execute(
        "SELECT sr FROM alpha_trials WHERE period = 'discovery' AND sr IS NOT NULL")]


def evaluate(conn, known_on, opens, closes, rule: Rule) -> dict:
    """Discovery-period evaluation of one rule; always logged."""
    t = trades(known_on, opens, closes, rule)
    s = summarize(t["ret"].to_numpy())
    log_trial(conn, rule, "discovery", s)
    return {"rule": rule.name(), **s}


def promote(conn, results: list[dict], min_n: int = 20, bar: float = 0.9) -> list[dict]:
    """ADR-0032 promotion bar: >= min_n trades, positive mean, Deflated Sharpe prob >= bar,
    with the deflation counting every discovery trial ever logged."""
    srs = trial_srs(conn)
    out = []
    for r in results:
        if r["sr"] is None or r["n"] < min_n or r["mean"] <= 0:
            continue
        d = deflated_sharpe(r["sr"], r["n"], r["skew"], r["kurt"], srs)
        if d >= bar:
            out.append({**r, "dsr": d})
    return sorted(out, key=lambda r: -r["dsr"])


def confirm(conn, known_on, opens, closes, rule: Rule, discovery_mean: float) -> dict:
    """The one holdout run for a promoted rule (logged as period 'holdout')."""
    t = trades(known_on, opens, closes, rule, start=HOLDOUT_START, end=date(2100, 1, 1),
               allow_holdout=True)
    s = summarize(t["ret"].to_numpy())
    log_trial(conn, rule, "holdout", s)
    ok = s["n"] > 0 and s["mean"] is not None and s["mean"] >= 0.5 * discovery_mean > 0
    return {"rule": rule.name(), **s, "passed": ok}


# ---------------------------------------------------------------- signals

def known_dates(conn: sqlite3.Connection, urls: Iterable[str]) -> dict[str, date]:
    """Day GDELT first saw each article (date_added), the earliest a trader could act."""
    urls = list(urls)
    out = {}
    for i in range(0, len(urls), 500):
        chunk = urls[i:i + 500]
        q = ("SELECT source_url, MIN(substr(date_added, 1, 8)) FROM candidates WHERE source_url"
             f" IN ({','.join('?' * len(chunk))}) GROUP BY source_url")
        for u, d in conn.execute(q, chunk):
            if d:
                out[u] = datetime.strptime(d, "%Y%m%d").date()
    return out


def signal_sets(conn, events, calendar, gap: int, features: dict) -> dict[str, list[date]]:
    """Named sets of known-on dates: Episode starts per type, plus Jev-flagged subsets."""
    from tremor.episodes import build_episodes, episode_starts
    from tremor.jev import flag

    starts = episode_starts(build_episodes(events, calendar, gap))
    known = known_dates(conn, [e.source_url for e in starts if e.source_url])

    def when(e):  # fall back to the day after the Event when GDELT has no record
        return known.get(e.source_url) or e.occurred_on

    sets: dict[str, list[date]] = {}
    for t in sorted({e.event_type for e in starts}):
        group = [e for e in starts if e.event_type == t]
        sets[f"start:{t}"] = [when(e) for e in group]
        for f in ("vessel_damaged", "energy_target", "escalation"):
            yes = [when(e) for e in group
                   if e.source_url in features and flag(features[e.source_url][f]) is True]
            if yes:
                sets[f"start:{t}+{f}"] = yes
    return sets


def summary_json(rows: list[dict]) -> str:
    return json.dumps(rows, indent=1, default=lambda o: asdict(o) if hasattr(o, "__dataclass_fields__") else str(o))
