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


def log_trial(conn: sqlite3.Connection, rule: Rule | str, period: str, s: dict) -> None:
    conn.executescript(SCHEMA)
    name = rule if isinstance(rule, str) else rule.name()
    conn.execute("INSERT INTO alpha_trials (at, rule, period, n, mean, sr, t, hit, skew, kurt)"
                 " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (datetime.now(UTC).isoformat(timespec="seconds"), name, period, s["n"],
                  s["mean"], s["sr"], s["t"], s["hit"], s["skew"], s["kurt"]))


def trial_srs(conn: sqlite3.Connection, period: str = "discovery") -> list[float]:
    """Sharpe ratios of every trial logged in one family: 'discovery' (per-trade rules) or
    'discovery-daily' (intensity rules, daily Sharpe), which can't share a deflation pool."""
    conn.executescript(SCHEMA)  # one per distinct rule (its latest run), so reruns don't count twice
    return [r[0] for r in conn.execute(
        "SELECT sr FROM alpha_trials a WHERE period = ? AND sr IS NOT NULL AND id = (SELECT"
        " MAX(id) FROM alpha_trials b WHERE b.rule = a.rule AND b.period = a.period)",
        (period,))]


def evaluate(conn, known_on, opens, closes, rule: Rule) -> dict:
    """Discovery-period evaluation of one rule; always logged."""
    t = trades(known_on, opens, closes, rule)
    s = summarize(t["ret"].to_numpy())
    log_trial(conn, rule, "discovery", s)
    return {"rule": rule.name(), **s}


def evaluate_fade(conn, signal, pairs, opens, closes, asset, hold, threshold, hedge) -> dict:
    name = f"{signal}|{asset}|{hold}d|fade>{threshold:.0%}{'|hedged' if hedge else ''}"
    t = fade_trades(pairs, opens, closes, asset, hold, threshold, hedge)
    s = summarize(t["ret"].to_numpy())
    log_trial(conn, name, "discovery", s)
    return {"rule": name, **s}


def evaluate_intensity(conn, known_on, opens, asset, window, ratio, label) -> dict:
    name = f"intensity:{label}|{asset}|{window}d>{ratio:g}x"
    s = summarize(intensity_returns(known_on, opens, asset, window, ratio=ratio).to_numpy())
    log_trial(conn, name, "discovery-daily", s)
    return {"rule": name, **s}


def promote(conn, results: list[dict], min_n: int = 20, bar: float = 0.9,
            period: str = "discovery") -> list[dict]:
    """ADR-0032 promotion bar: >= min_n trades, positive mean, Deflated Sharpe prob >= bar,
    with the deflation counting every trial ever logged in the same family."""
    srs = trial_srs(conn, period)
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


def signal_sets(conn, events, calendar, gap: int,
                features: dict) -> dict[str, list[tuple[date, date]]]:
    """Named sets of (occurred_on, known_on) pairs: Episode starts per type, Jev-flagged subsets
    of them, and every Event per type ("all:", for the intensity rules)."""
    from tremor.episodes import build_episodes, episode_starts
    from tremor.jev import flag

    starts = episode_starts(build_episodes(events, calendar, gap))
    known = known_dates(conn, [e.source_url for e in events if e.source_url])

    def pair(e):  # seed Events have no GDELT record: treat them as known on the day they occurred
        return (e.occurred_on, known.get(e.source_url) or e.occurred_on)

    sets: dict[str, list[tuple[date, date]]] = {}
    for t in sorted({e.event_type for e in events}):
        sets[f"all:{t}"] = [pair(e) for e in events if e.event_type == t]
        group = [e for e in starts if e.event_type == t]
        sets[f"start:{t}"] = [pair(e) for e in group]
        for f in ("vessel_damaged", "energy_target", "escalation"):
            yes = [pair(e) for e in group
                   if e.source_url in features and flag(features[e.source_url][f]) is True]
            if yes:
                sets[f"start:{t}+{f}"] = yes
    return sets


# ---------------------------------------------------------------- fade and intensity (ADR-0032)

def fade_trades(signals: Iterable[tuple[date, date]], opens, closes, asset: str, hold: int,
                threshold: float, hedge: bool = False, start: date = DISCOVERY_START,
                end: date = HOLDOUT_START, allow_holdout: bool = False) -> pd.DataFrame:
    """Trade against the move already made. For each (occurred_on, known_on): the spike is the
    asset's close on the known day over its close the day before the Event (all known by the
    entry open). If |spike| >= threshold, enter against it at the next open, hold `hold` days."""
    if end > HOLDOUT_START and not allow_holdout:
        raise HoldoutError(f"dates from {HOLDOUT_START} on are the locked holdout (ADR-0032)")
    o, c = opens[asset].dropna(), closes[asset].dropna()
    cal = o.index.intersection(c.index)
    if hedge:
        cal = cal.intersection(opens["SPY"].dropna().index)
    cost = 2 * COST_BP[asset] / 1e4 + (2 * COST_BP["SPY"] / 1e4 if hedge else 0)
    rows, busy_until = [], -1
    for occ, k in sorted(set(signals), key=lambda s: s[1]):
        if not (start <= k < end):
            continue
        before = int(cal.searchsorted(pd.Timestamp(occ))) - 1    # last close before the Event
        known = int(cal.searchsorted(pd.Timestamp(k), side="right")) - 1  # close on/before k
        i, j = known + 1, known + hold
        if before < 0 or known < before or i <= busy_until or j >= len(cal) \
                or cal[j].date() >= end:
            continue
        spike = c[cal[known]] / c[cal[before]] - 1
        if abs(spike) < threshold:
            continue
        r = c[cal[j]] / o[cal[i]] - 1
        if hedge:
            r -= closes["SPY"][cal[j]] / opens["SPY"][cal[i]] - 1
        rows.append((k, cal[i].date(), cal[j].date(), -np.sign(spike) * r - cost))
        busy_until = j
    return pd.DataFrame(rows, columns=["known_on", "entry", "exit", "ret"])


def intensity_returns(known_on: Iterable[date], opens, asset: str, window: int = 20,
                      base: int = 250, ratio: float = 1.0, start: date = DISCOVERY_START,
                      end: date = HOLDOUT_START, allow_holdout: bool = False) -> pd.Series:
    """Daily open-to-open returns of holding `asset` while the count of Events known in the last
    `window` trading days exceeds `ratio` x its average over the prior `base` days. The position
    for the open of day t uses only Events known on or before day t-1. Costs on each change."""
    if end > HOLDOUT_START and not allow_holdout:
        raise HoldoutError(f"dates from {HOLDOUT_START} on are the locked holdout (ADR-0032)")
    o = opens[asset].dropna()
    cal = o.index
    hits = pd.Series(0.0, index=cal)
    for k in known_on:
        i = int(cal.searchsorted(pd.Timestamp(k)))
        if i < len(cal):
            hits.iloc[i] += 1
    recent = hits.rolling(window).sum()
    normal = recent.shift(window).rolling(base).mean()
    on = (recent > ratio * normal) & (normal > 0)
    pos = on.shift(1, fill_value=False).astype(float)  # decided at t-1, held from open t
    ret = o.shift(-1) / o - 1                           # open t -> open t+1
    daily = pos * ret - pos.diff().abs().fillna(0) * COST_BP[asset] / 1e4
    keep = (cal.date >= start) & (cal.date < end)
    return daily[keep].dropna()


def summary_json(rows: list[dict]) -> str:
    return json.dumps(rows, indent=1, default=lambda o: asdict(o) if hasattr(o, "__dataclass_fields__") else str(o))
