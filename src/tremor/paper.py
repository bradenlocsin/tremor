"""Paper trading of rules that passed the locked holdout (ADR-0032, last gate).

The algorithm trades and the website only shows what it did. Orders are insert-only and
hash-chained, so a deleted or edited order breaks the chain and shows. An order is created the
day a signal is detected and enters at the open of the first trading day *after* that day, so a
late job can never back-date a trade. Only signals first seen after a rule was activated count.

Sizing for v1: a fixed $1,000 per trade from a notional $10,000 account; costs as in the
research (alpha.COST_BP), both ways.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pandas as pd

from tremor.alpha import COST_BP

START_CASH = 10_000.0
SIZE_USD = 1_000.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_rules (
  rule_id TEXT PRIMARY KEY, spec TEXT NOT NULL, activated_on TEXT NOT NULL, why TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_orders (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL,
  created_on TEXT NOT NULL, rule_id TEXT NOT NULL, asset TEXT NOT NULL, direction INTEGER NOT NULL,
  hold INTEGER NOT NULL, hedge INTEGER NOT NULL, size_usd REAL NOT NULL, signal TEXT NOT NULL,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_fills (
  order_id TEXT NOT NULL, leg TEXT NOT NULL, date TEXT NOT NULL, price REAL NOT NULL,
  filled_at TEXT NOT NULL, PRIMARY KEY (order_id, leg)
);
CREATE TRIGGER IF NOT EXISTS paper_orders_no_update BEFORE UPDATE ON paper_orders
  BEGIN SELECT RAISE(ABORT, 'paper orders are insert-only'); END;
CREATE TRIGGER IF NOT EXISTS paper_orders_no_delete BEFORE DELETE ON paper_orders
  BEGIN SELECT RAISE(ABORT, 'paper orders are insert-only'); END;
"""


@dataclass(frozen=True)
class Spec:
    """What a paper rule trades. `kind` is 'drift' (fixed direction) or 'fade' (against the
    move since the day before the Event, if at least `threshold`)."""
    signal: str          # e.g. "start:shipping_attack" or "start:shipping_attack+vessel_damaged"
    asset: str
    hold: int
    hedge: bool = False
    kind: str = "drift"
    direction: int = 1
    threshold: float = 0.0


def _hash(prev: str, row: dict) -> str:
    return hashlib.sha256((prev + json.dumps(row, sort_keys=True)).encode()).hexdigest()


def activate(conn: sqlite3.Connection, rule_id: str, spec: Spec, why: str,
             on: date | None = None) -> None:
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO paper_rules VALUES (?, ?, ?, ?)",
                 (rule_id, json.dumps(spec.__dict__), (on or datetime.now(UTC).date())
                  .isoformat(), why))
    conn.commit()


def rules(conn: sqlite3.Connection) -> list[tuple[str, Spec, date]]:
    conn.executescript(SCHEMA)
    return [(r, Spec(**json.loads(s)), date.fromisoformat(a))
            for r, s, a, _ in conn.execute("SELECT * FROM paper_rules")]


def place(conn: sqlite3.Connection, rule_id: str, spec: Spec, signal: dict, direction: int,
          today: date, now: datetime | None = None) -> bool:
    """Insert one order (idempotent per rule and signal). Returns True if it was new."""
    conn.executescript(SCHEMA)
    order_id = hashlib.sha256(f"{rule_id}|{signal['key']}".encode()).hexdigest()[:16]
    if conn.execute("SELECT 1 FROM paper_orders WHERE order_id = ?", (order_id,)).fetchone():
        return False
    prev = conn.execute("SELECT hash FROM paper_orders ORDER BY seq DESC LIMIT 1").fetchone()
    prev = prev[0] if prev else "genesis"
    row = {"order_id": order_id, "created_at": (now or datetime.now(UTC)).isoformat(
        timespec="seconds"), "created_on": today.isoformat(), "rule_id": rule_id,
        "asset": spec.asset, "direction": direction, "hold": spec.hold, "hedge": int(spec.hedge),
        "size_usd": SIZE_USD, "signal": json.dumps(signal, sort_keys=True, default=str)}
    conn.execute(
        "INSERT INTO paper_orders (order_id, created_at, created_on, rule_id, asset, direction,"
        " hold, hedge, size_usd, signal, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (*row.values(), prev, _hash(prev, row)))
    return True


def chain_ok(conn: sqlite3.Connection) -> bool:
    conn.executescript(SCHEMA)
    prev = "genesis"
    cols = ["order_id", "created_at", "created_on", "rule_id", "asset", "direction", "hold",
            "hedge", "size_usd", "signal"]
    for r in conn.execute(f"SELECT {', '.join(cols)}, prev_hash, hash FROM paper_orders"
                          " ORDER BY seq"):
        row = dict(zip(cols, r[:10]))
        if r[10] != prev or r[11] != _hash(prev, row):
            return False
        prev = r[11]
    return True


def generate(conn, signals: dict[str, list[dict]], closes: pd.DataFrame, today: date) -> int:
    """Place orders for new signals of every active rule. `signals` maps a signal name to dicts
    with 'key', 'occurred_on' and 'known_on'. Only signals known on or after activation count."""
    new = 0
    for rule_id, spec, active_on in rules(conn):
        for s in signals.get(spec.signal, []):
            if s["known_on"] < active_on or s["known_on"] > today:
                continue
            direction = spec.direction
            if spec.kind == "fade":
                c = closes[spec.asset].dropna()
                before = c[c.index < pd.Timestamp(s["occurred_on"])]
                upto = c[c.index <= pd.Timestamp(today)]
                if before.empty or upto.empty:
                    continue
                spike = upto.iloc[-1] / before.iloc[-1] - 1
                if abs(spike) < spec.threshold:
                    continue
                direction = -1 if spike > 0 else 1
            new += place(conn, rule_id, spec, s, direction, today)
    conn.commit()
    return new


def fill(conn, opens: pd.DataFrame, closes: pd.DataFrame, now: datetime | None = None) -> int:
    """Record fills from real prices: entry at the first open after the order's day, exit at
    the close `hold` trading days later (SPY legs too for hedged orders)."""
    conn.executescript(SCHEMA)
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    done = {(o, leg) for o, leg in conn.execute("SELECT order_id, leg FROM paper_fills")}
    n = 0
    for oid, created_on, asset, hold, hedge in conn.execute(
            "SELECT order_id, created_on, asset, hold, hedge FROM paper_orders").fetchall():
        for leg_asset, prefix in [(asset, "")] + ([("SPY", "spy_")] if hedge else []):
            o, c = opens[leg_asset].dropna(), closes[leg_asset].dropna()
            cal = o.index.intersection(c.index)
            i = int(cal.searchsorted(pd.Timestamp(created_on), side="right"))
            j = i + hold - 1
            for leg, k, px in ((prefix + "entry", i, o), (prefix + "exit", j, c)):
                if (oid, leg) in done or k >= len(cal):
                    continue
                conn.execute("INSERT INTO paper_fills VALUES (?, ?, ?, ?, ?)",
                             (oid, leg, cal[k].date().isoformat(), float(px[cal[k]]), stamp))
                n += 1
    conn.commit()
    return n


def live_signals(conn, events, calendar, gap: int, features: dict) -> dict[str, list[dict]]:
    """The same signal sets as the research (alpha.signal_sets), keyed by article so each
    signal places at most one order per rule."""
    from tremor.alpha import known_dates
    from tremor.episodes import build_episodes, episode_starts
    from tremor.jev import flag

    starts = episode_starts(build_episodes(events, calendar, gap))
    known = known_dates(conn, [e.source_url for e in starts if e.source_url])
    out: dict[str, list[dict]] = {}
    for e in starts:
        s = {"key": e.source_url or e.id, "occurred_on": e.occurred_on,
             "known_on": known.get(e.source_url) or e.occurred_on, "title": e.title}
        out.setdefault(f"start:{e.event_type}", []).append(s)
        f = features.get(e.source_url, {})
        for name in ("vessel_damaged", "energy_target", "escalation"):
            if name in f and flag(f[name]) is True:
                out.setdefault(f"start:{e.event_type}+{name}", []).append(s)
    return out


def daily_step(conn, cfg) -> str:
    """Scheduled once a day after prices: refresh research prices, place new orders, fill."""
    from datetime import timedelta

    from tremor import alpha, jev
    from tremor.events import load_events

    active = rules(conn)
    if not active:
        return "no rules active yet"
    tickers = sorted({s.asset for _, s, _ in active} | {"SPY"})
    alpha.fetch_prices(conn, tickers, start=(datetime.now(UTC) - timedelta(days=14)).date()
                       .isoformat())
    opens, closes = alpha.load_ohlc(conn)
    today = datetime.now(UTC).date()
    sigs = live_signals(conn, load_events(conn, region="red_sea"), closes.index,
                        cfg.event_study.episode_gap_trading_days, jev.answers(conn, "features"))
    placed = generate(conn, sigs, closes, today)
    filled = fill(conn, opens, closes)
    return f"{placed} new orders, {filled} fills, chain {'ok' if chain_ok(conn) else 'BROKEN'}"


def ledger(conn) -> pd.DataFrame:
    """One row per order with fills and, once closed, return after costs and P&L."""
    conn.executescript(SCHEMA)
    orders = pd.read_sql("SELECT order_id, created_at, rule_id, asset, direction, hold, hedge,"
                         " size_usd FROM paper_orders ORDER BY seq", conn)
    fills = pd.read_sql("SELECT order_id, leg, date, price FROM paper_fills", conn)
    if orders.empty:
        return orders
    px = fills.pivot(index="order_id", columns="leg", values="price")
    dt = fills.pivot(index="order_id", columns="leg", values="date")
    out = orders.set_index("order_id")
    for leg in ("entry", "exit", "spy_entry", "spy_exit"):
        out[leg] = px[leg] if leg in px else None
        out[leg + "_date"] = dt[leg] if leg in dt else None
    def ret(r):
        if pd.isna(r["exit"]) or pd.isna(r["entry"]):
            return None
        x = r["direction"] * (r["exit"] / r["entry"] - 1) - 2 * COST_BP[r["asset"]] / 1e4
        if r["hedge"]:
            if pd.isna(r["spy_exit"]) or pd.isna(r["spy_entry"]):
                return None
            x -= r["spy_exit"] / r["spy_entry"] - 1 + 2 * COST_BP["SPY"] / 1e4
        return x
    out["ret"] = out.apply(ret, axis=1)
    out["pnl"] = out["ret"] * out["size_usd"]
    out["status"] = ["closed" if pd.notna(r) else "open" if pd.notna(e) else "pending"
                     for r, e in zip(out["ret"], out["entry"])]
    return out.reset_index()
