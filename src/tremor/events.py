"""Events: the core unit (see GLOSSARY.md). Storage helpers and the hand-entered seed set."""

from __future__ import annotations

import json
import sqlite3
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from tremor.config import REPO_ROOT
from tremor.taxonomy import Taxonomy, default_taxonomy

SEED_PATH = REPO_ROOT / "config" / "seed_events.toml"


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    event_type: str
    region: str
    occurred_on: date
    reported_at: str | None = None
    actors: tuple[str, ...] = field(default_factory=tuple)
    summary: str | None = None
    source_url: str | None = None
    source_name: str | None = None
    license: str = "commercial"
    fidelity: str = "full"
    origin: str = "seed"
    refinement_path: str | None = "seed"
    model: str | None = None
    taxonomy_version: int | None = None
    severity: int | None = None
    assets: tuple[str, ...] = field(default_factory=tuple)
    lat: float | None = None
    lon: float | None = None


def load_seed_events(path: Path = SEED_PATH, taxonomy: Taxonomy | None = None) -> list[Event]:
    """Parse the seed file, validating Event types and assigning Regions from coordinates."""
    tax = taxonomy or default_taxonomy()
    raw = tomllib.loads(Path(path).read_text())
    events = []
    for e in raw["events"]:
        tax.event_type(e["event_type"])  # raises on unknown types
        region = tax.region_for(e["lat"], e["lon"])
        if region is None:
            raise ValueError(f"seed Event outside every Region: {e['title']}")
        d = date.fromisoformat(e["date"])
        events.append(
            Event(
                id=f"seed-{d.isoformat()}-{e['event_type']}",
                title=e["title"],
                event_type=e["event_type"],
                region=region.id,
                occurred_on=d,
                reported_at=d.isoformat(),
                actors=tuple(e.get("actors", [])),
                source_url=e["source_url"],
                source_name="Wikipedia",
                license="commercial",
                fidelity="full",
                origin="seed",
                refinement_path="seed",
                taxonomy_version=tax.version,
                lat=e["lat"],
                lon=e["lon"],
            )
        )
    return events


COLUMNS = (
    "id", "title", "event_type", "region", "occurred_on", "reported_at", "actors", "summary",
    "source_url", "source_name", "license", "fidelity", "origin", "refinement_path", "model",
    "taxonomy_version", "severity", "assets", "lat", "lon",
)


def save_events(conn: sqlite3.Connection, events: list[Event]) -> int:
    rows = [
        (
            e.id, e.title, e.event_type, e.region, e.occurred_on.isoformat(), e.reported_at,
            json.dumps(list(e.actors)), e.summary, e.source_url, e.source_name, e.license,
            e.fidelity, e.origin, e.refinement_path, e.model, e.taxonomy_version, e.severity,
            json.dumps(list(e.assets)), e.lat, e.lon,
        )
        for e in events
    ]
    conn.executemany(
        f"INSERT OR REPLACE INTO events ({', '.join(COLUMNS)})"
        f" VALUES ({', '.join('?' * len(COLUMNS))})",
        rows,
    )
    conn.commit()
    return len(rows)


def load_events(
    conn: sqlite3.Connection, event_type: str | None = None, region: str | None = None
) -> list[Event]:
    sql, params = "SELECT * FROM events WHERE 1=1", []
    if event_type:
        sql += " AND event_type = ?"
        params.append(event_type)
    if region:
        sql += " AND region = ?"
        params.append(region)
    sql += " ORDER BY occurred_on"
    cols = [c[1] for c in conn.execute("PRAGMA table_info(events)")]
    out = []
    for row in conn.execute(sql, params):
        r = dict(zip(cols, row))
        r["occurred_on"] = date.fromisoformat(r["occurred_on"])
        r["actors"] = tuple(json.loads(r["actors"] or "[]"))
        r["assets"] = tuple(json.loads(r.get("assets") or "[]"))
        out.append(Event(**r))
    return out
