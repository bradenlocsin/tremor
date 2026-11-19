"""Sensor context: daily chokepoint transits (ADR-0023).

Source: IMF PortWatch daily chokepoint transit estimates (from ship AIS signals), the same
upstream gods-eye-view's chokepoints layer reads. gods-eye-view's own /api is served by its
local server rather than a public host, so TREMOR queries the keyless PortWatch ArcGIS tables
directly. IMF terms: reuse with attribution, not for resale → License tag non-commercial.

v1 uses this as context only: shown on the dashboard and passed to the Recommendation
rationale, never used in the quant Analysis.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

SERVICES = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
DAILY = f"{SERVICES}/Daily_Chokepoints_Data/FeatureServer/0/query"
SOURCE = "IMF PortWatch (International Monetary Fund and University of Oxford)"
LICENSE = "non-commercial"
ATTRIBUTION = ("Chokepoint transits: IMF PortWatch (International Monetary Fund and University "
               "of Oxford), estimated from ship AIS signals")
HISTORY_START = date(2019, 1, 1)

# Which chokepoints describe each Region. The Cape of Good Hope is where Red Sea traffic diverts.
REGION_CHOKEPOINTS = {
    "red_sea": {"chokepoint4": "Bab el-Mandeb Strait", "chokepoint1": "Suez Canal",
                "chokepoint7": "Cape of Good Hope"},
    "hormuz": {"chokepoint6": "Strait of Hormuz"},
    "taiwan_strait": {"chokepoint11": "Taiwan Strait"},
    "black_sea": {"chokepoint3": "Bosporus Strait"},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS chokepoint_transits (
    portid       TEXT NOT NULL,
    portname     TEXT NOT NULL,
    date         TEXT NOT NULL,
    n_total      INTEGER,
    n_tanker     INTEGER,
    n_container  INTEGER,
    n_dry_bulk   INTEGER,
    source       TEXT NOT NULL,
    license      TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (portid, date)
);
"""


def _query(params: dict) -> dict:
    url = DAILY + "?" + urlencode(params)
    with urlopen(Request(url, headers={"User-Agent": "tremor-research/0.1"}), timeout=60) as r:
        payload = json.loads(r.read())
    if "error" in payload:  # ArcGIS answers refusals with HTTP 200 and an error object
        raise RuntimeError(f"PortWatch refused the query: {payload['error']}")
    return payload


def fetch_daily(portid: str, start: date, end: date) -> list[dict]:
    """Daily rows for one chokepoint, windowed by year (the service refuses offset paging)."""
    rows: list[dict] = []
    s = start
    while s <= end:
        e = min(date(s.year, 12, 31), end)
        payload = _query({
            "where": f"portid='{portid}' AND date >= DATE '{s}' AND date <= DATE '{e}'",
            "outFields": "date,portid,portname,n_total,n_tanker,n_container,n_dry_bulk",
            "orderByFields": "date ASC",
            "resultRecordCount": "2000",
            "returnGeometry": "false",
            "f": "json",
        })
        rows += [f["attributes"] for f in payload.get("features", [])]
        s = e + timedelta(days=1)
    return rows


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def save_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.executemany(
        "INSERT OR REPLACE INTO chokepoint_transits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(r["portid"], r["portname"], str(r["date"])[:10], r.get("n_total"), r.get("n_tanker"),
          r.get("n_container"), r.get("n_dry_bulk"), SOURCE, LICENSE, now) for r in rows],
    )
    conn.commit()
    return len(rows)


def record_chokepoints(conn: sqlite3.Connection, region: str = "red_sea", fetch=fetch_daily) -> int:
    """Daily recorder: fetch each Region chokepoint's new days (first run: since 2019)."""
    ensure_schema(conn)
    added = 0
    for portid in REGION_CHOKEPOINTS.get(region, {}):
        last = conn.execute(
            "SELECT MAX(date) FROM chokepoint_transits WHERE portid = ?", (portid,)
        ).fetchone()[0]
        start = date.fromisoformat(last) - timedelta(days=14) if last else HISTORY_START
        added += save_rows(conn, fetch(portid, start, date.today()))  # re-read 2 weeks: revisions
    return added


def transits(conn: sqlite3.Connection, region: str = "red_sea") -> pd.DataFrame:
    """Wide frame: one column of total daily transits per chokepoint name."""
    ensure_schema(conn)
    ports = REGION_CHOKEPOINTS.get(region, {})
    if not ports:
        return pd.DataFrame()
    df = pd.read_sql_query(
        f"SELECT date, portname, n_total FROM chokepoint_transits"
        f" WHERE portid IN ({','.join('?' * len(ports))})", conn, params=list(ports))
    if df.empty:
        return df
    wide = df.pivot(index="date", columns="portname", values="n_total")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


@dataclass(frozen=True)
class ChokepointContext:
    portname: str
    as_of: date
    recent_mean: float      # 7-day mean up to as_of
    baseline_mean: float    # the 90 days before that

    @property
    def change(self) -> float:
        return self.recent_mean / self.baseline_mean - 1 if self.baseline_mean else float("nan")

    def sentence(self) -> str:
        return (f"{self.portname}: {self.recent_mean:.0f} transits/day over the 7 days to "
                f"{self.as_of}, vs {self.baseline_mean:.0f}/day in the 90 days before "
                f"({self.change:+.0%})")


def context(wide: pd.DataFrame, when: date) -> list[ChokepointContext]:
    """7-day vs prior-90-day transit means as of `when` (or the latest day published before it)."""
    out = []
    if wide.empty:
        return out
    for port in wide.columns:
        s = wide[port].dropna()
        s = s[s.index <= pd.Timestamp(when)]
        if len(s) < 97:
            continue
        recent, base = s.iloc[-7:], s.iloc[-97:-7]
        out.append(ChokepointContext(port, s.index[-1].date(), float(recent.mean()),
                                     float(base.mean())))
    return out


def context_text(conn: sqlite3.Connection, region: str, when: date) -> str:
    """One line for the Recommendation rationale (context only, never Analysis)."""
    parts = [c.sentence() for c in context(transits(conn, region), when)]
    return ("; ".join(parts) + f". {ATTRIBUTION}.") if parts else ""
