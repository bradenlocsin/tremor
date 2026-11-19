"""GDELT Candidate ingestion (ADR-0007, ADR-0015, ADR-0017).

* Backfill: GDELT 1.0 daily event files (one per day, with source URLs since 2013).
* Live: GDELT 2.0 15-minute event files, pulled hourly.

Only rows whose CAMEO code and source URL match an Event type in the taxonomy, and whose
action location falls inside a Region, are kept as Candidates. Every processed file is recorded
so both jobs are resumable and never reprocess a file.

GDELT is open data ("free for any use" with citation), so Candidates carry the commercial
License tag. Re-check the terms at https://www.gdeltproject.org/about.html#termsofuse.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.request import Request, urlopen

from tremor.taxonomy import Taxonomy

V1_DAILY_URL = "https://data.gdeltproject.org/events/{day}.export.CSV.zip"
V2_URL = "https://data.gdeltproject.org/gdeltv2/{stamp}.export.CSV.zip"
LICENSE = "commercial"
USER_AGENT = "tremor-research/0.1"

# Column positions, checked against real files on 2026-11-19.
COLUMNS = {
    "v1": dict(n=58, actor1=6, actor2=16, code=26, goldstein=30, mentions=31, sources=32,
               articles=33, tone=34, place=50, lat=53, lon=54, added=56, url=57),
    "v2": dict(n=61, actor1=6, actor2=16, code=26, goldstein=30, mentions=31, sources=32,
               articles=33, tone=34, place=52, lat=56, lon=57, added=59, url=60),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    gdelt_id        TEXT PRIMARY KEY,
    event_date      TEXT NOT NULL,
    event_code      TEXT NOT NULL,
    candidate_types TEXT NOT NULL,      -- JSON list of taxonomy Event type ids
    region          TEXT NOT NULL,
    actor1          TEXT,
    actor2          TEXT,
    place           TEXT,
    lat             REAL,
    lon             REAL,
    goldstein       REAL,
    num_mentions    INTEGER,
    num_sources     INTEGER,
    num_articles    INTEGER,
    avg_tone        REAL,
    source_url      TEXT NOT NULL,
    date_added      TEXT,
    ingested_from   TEXT NOT NULL,      -- GDELT file name (Provenance)
    license         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'new'   -- new | refined | rejected | duplicate
);
CREATE INDEX IF NOT EXISTS candidates_url ON candidates(source_url);
CREATE INDEX IF NOT EXISTS candidates_status ON candidates(status, region);

CREATE TABLE IF NOT EXISTS gdelt_files (
    name        TEXT PRIMARY KEY,
    rows_kept   INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Candidate:
    gdelt_id: str
    event_date: str
    event_code: str
    candidate_types: tuple[str, ...]
    region: str
    actor1: str
    actor2: str
    place: str
    lat: float
    lon: float
    goldstein: float | None
    num_mentions: int
    num_sources: int
    num_articles: int
    avg_tone: float | None
    source_url: str
    date_added: str


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _f(v: str) -> float | None:
    try:
        return float(v)
    except ValueError:
        return None


def parse_rows(text: str, version: str, tax: Taxonomy) -> list[Candidate]:
    """Filter one GDELT export file's rows down to Candidates."""
    c = COLUMNS[version]
    out = []
    for row in csv.reader(io.StringIO(text), delimiter="\t"):
        if len(row) < c["n"]:
            continue
        lat, lon = _f(row[c["lat"]]), _f(row[c["lon"]])
        if lat is None or lon is None:
            continue
        region = tax.region_for(lat, lon)
        if region is None:
            continue
        url = row[c["url"]]
        types = tax.candidate_types(row[c["code"]], url)
        if not types or not url.startswith("http"):
            continue
        out.append(
            Candidate(
                gdelt_id=row[0],
                event_date=f"{row[1][:4]}-{row[1][4:6]}-{row[1][6:8]}",
                event_code=row[c["code"]],
                candidate_types=tuple(t.id for t in types),
                region=region.id,
                actor1=row[c["actor1"]],
                actor2=row[c["actor2"]],
                place=row[c["place"]],
                lat=lat,
                lon=lon,
                goldstein=_f(row[c["goldstein"]]),
                num_mentions=int(row[c["mentions"]] or 0),
                num_sources=int(row[c["sources"]] or 0),
                num_articles=int(row[c["articles"]] or 0),
                avg_tone=_f(row[c["tone"]]),
                source_url=url,
                date_added=row[c["added"]],
            )
        )
    return out


def download(url: str, retries: int = 3) -> bytes | None:
    """Fetch a zip; None if GDELT has no file for that slot (404)."""
    for attempt in range(retries):
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", None) == 404:
                return None
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return None


def unzip_text(blob: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(blob))
    return z.read(z.namelist()[0]).decode("utf-8", "replace")


def save_candidates(
    conn: sqlite3.Connection, cands: list[Candidate], file_name: str
) -> int:
    rows = [
        (
            x.gdelt_id, x.event_date, x.event_code, json.dumps(list(x.candidate_types)),
            x.region, x.actor1, x.actor2, x.place, x.lat, x.lon, x.goldstein, x.num_mentions,
            x.num_sources, x.num_articles, x.avg_tone, x.source_url, x.date_added, file_name,
            LICENSE,
        )
        for x in cands
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO candidates (gdelt_id, event_date, event_code, candidate_types,"
        " region, actor1, actor2, place, lat, lon, goldstein, num_mentions, num_sources,"
        " num_articles, avg_tone, source_url, date_added, ingested_from, license)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute(
        "INSERT OR REPLACE INTO gdelt_files VALUES (?, ?, ?)",
        (file_name, len(rows), datetime.now(UTC).isoformat(timespec="seconds")),
    )
    conn.commit()
    return len(rows)


def done_files(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM gdelt_files")}


def _process(name: str, url: str, version: str, tax: Taxonomy) -> tuple[str, list[Candidate]]:
    blob = download(url)
    return name, (parse_rows(unzip_text(blob), version, tax) if blob else [])


def backfill(
    conn: sqlite3.Connection, tax: Taxonomy, start: date, end: date, workers: int = 6,
    log=print,
) -> int:
    """Ingest GDELT 1.0 daily files from start to end (inclusive). Resumable."""
    ensure_schema(conn)
    done = done_files(conn)
    jobs = []
    d = start
    while d <= end:
        name = f"v1/{d:%Y%m%d}"
        if name not in done:
            jobs.append((name, V1_DAILY_URL.format(day=f"{d:%Y%m%d}")))
        d += timedelta(days=1)
    total = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_process, n, u, "v1", tax): n for n, u in jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            name = futures[fut]
            try:
                _, cands = fut.result()
            except Exception as e:  # noqa: BLE001
                log(f"  {name}: FAILED ({e}); will retry on the next run")
                continue
            total += save_candidates(conn, cands, name)
            if i % 100 == 0 or i == len(jobs):
                log(f"  {i}/{len(jobs)} files, {total} Candidates kept")
    return total


def v2_stamps_since(last: datetime | None, now: datetime, lookback_hours: int = 3) -> list[str]:
    """15-minute GDELT 2.0 file stamps after `last` (or the last few hours), up to now - 15m."""
    end = now.replace(minute=now.minute - now.minute % 15, second=0, microsecond=0)
    end -= timedelta(minutes=15)  # the newest slot may not be published yet
    t = (last + timedelta(minutes=15)) if last else end - timedelta(hours=lookback_hours)
    out = []
    while t <= end:
        out.append(t.strftime("%Y%m%d%H%M%S"))
        t += timedelta(minutes=15)
    return out


def pull_latest(conn: sqlite3.Connection, tax: Taxonomy, now: datetime | None = None) -> int:
    """Hourly job: ingest every GDELT 2.0 15-minute file not yet processed."""
    ensure_schema(conn)
    now = now or datetime.now(UTC).replace(tzinfo=None)
    row = conn.execute("SELECT MAX(name) FROM gdelt_files WHERE name LIKE 'v2/%'").fetchone()
    last = datetime.strptime(row[0][3:], "%Y%m%d%H%M%S") if row and row[0] else None
    total = 0
    for stamp in v2_stamps_since(last, now):
        name, cands = _process(f"v2/{stamp}", V2_URL.format(stamp=stamp), "v2", tax)
        total += save_candidates(conn, cands, name)
    return total


# Candidates whose event date is far older than the day GDELT added them are retrospective
# mentions ("in 2005, ..."), not new Events. Refinement and Eval sampling skip them.
FRESH_SQL = "event_date >= date(substr(date_added,1,4)||'-'||substr(date_added,5,2)||'-'||substr(date_added,7,2), '-30 days')"


def candidate_counts(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT region, candidate_types, COUNT(*), COUNT(DISTINCT source_url) FROM candidates"
        " GROUP BY region, candidate_types ORDER BY region, 3 DESC"
    ).fetchall()
