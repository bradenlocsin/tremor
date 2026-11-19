"""The Eval set (ADR-0019): ~100 Candidates labeled blind, used to score refinement.

Labels come from the author (dashboard labeling page) or from the Codex model panel (ADR-0025,
tremor.panel); eval_labels.labeled_by records which.

* sample(): a stratified sample of distinct Candidate URLs (spread over years and GDELT types)
* labels are never pre-filled from TREMOR's own refinement output
* score(): runs a refiner over the labeled items (writes nothing to Events) and records accuracy
  per field plus the noise-rejection rate, keyed by model, prompt hash and taxonomy version
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from tremor.config import Config
from tremor.gdelt import FRESH_SQL
from tremor.refine import Refiner, fetch_article, record_spend, system_prompt, user_prompt
from tremor.taxonomy import Taxonomy

SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_items (
    source_url  TEXT PRIMARY KEY,
    event_date  TEXT NOT NULL,
    region      TEXT NOT NULL,
    candidate   TEXT NOT NULL,      -- JSON of the Candidate row used to build the prompt
    sampled_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_labels (
    source_url     TEXT PRIMARY KEY,
    is_real_event  INTEGER,         -- 1 / 0 / NULL when unsure
    event_type     TEXT,            -- taxonomy id or 'none'
    region         TEXT,            -- Region id or 'none'
    duplicate      INTEGER NOT NULL DEFAULT 0,
    unsure         INTEGER NOT NULL DEFAULT 0,
    note           TEXT,
    labeled_at     TEXT NOT NULL,
    labeled_by     TEXT NOT NULL DEFAULT 'author'   -- 'author' or 'panel:<model>' (ADR-0025)
);
CREATE TABLE IF NOT EXISTS eval_runs (
    run_id            TEXT PRIMARY KEY,
    model             TEXT NOT NULL,
    prompt_hash       TEXT NOT NULL,
    taxonomy_version  INTEGER NOT NULL,
    n                 INTEGER NOT NULL,
    real_accuracy     REAL,
    type_accuracy     REAL,
    region_accuracy   REAL,
    noise_rejection   REAL,
    created_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_predictions (
    run_id      TEXT NOT NULL,
    source_url  TEXT NOT NULL,
    is_real     INTEGER NOT NULL,
    event_type  TEXT NOT NULL,
    PRIMARY KEY (run_id, source_url)
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(eval_labels)")}
    if "labeled_by" not in cols:
        conn.execute("ALTER TABLE eval_labels ADD COLUMN labeled_by TEXT NOT NULL DEFAULT 'author'")
    run_cols = {r[1] for r in conn.execute("PRAGMA table_info(eval_runs)")}
    for col in ("keep_precision", "keep_recall"):
        if col not in run_cols:
            conn.execute(f"ALTER TABLE eval_runs ADD COLUMN {col} REAL")
    pred_cols = {r[1] for r in conn.execute("PRAGMA table_info(eval_predictions)")}
    if "in_region" not in pred_cols:
        conn.execute("ALTER TABLE eval_predictions ADD COLUMN in_region INTEGER")


def sample(conn: sqlite3.Connection, region: str, n: int = 100, seed: int = 7) -> int:
    """Add a stratified sample of unlabeled Candidate URLs. Returns how many were added."""
    ensure_schema(conn)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"""
        SELECT source_url, MIN(event_date) AS event_date, region, candidate_types,
               MAX(actor1) AS actor1, MAX(actor2) AS actor2, MAX(place) AS place,
               AVG(lat) AS lat, AVG(lon) AS lon, SUM(num_articles) AS coverage,
               substr(MIN(date_added), 1, 4) AS added_year
        FROM candidates WHERE region = ? AND {FRESH_SQL}
          AND source_url NOT IN (SELECT source_url FROM eval_items)
        GROUP BY source_url
        """,
        (region,),
    ).fetchall()
    conn.row_factory = None
    strata: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        d = dict(r)
        strata.setdefault((d["added_year"], d["candidate_types"]), []).append(d)
    rng = random.Random(seed)
    for bucket in strata.values():
        rng.shuffle(bucket)
    picked: list[dict] = []
    keys = sorted(strata)
    while len(picked) < n and any(strata[k] for k in keys):  # round-robin across strata
        for k in keys:
            if strata[k] and len(picked) < n:
                picked.append(strata[k].pop())
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.executemany(
        "INSERT OR IGNORE INTO eval_items VALUES (?, ?, ?, ?, ?)",
        [(p["source_url"], p["event_date"], p["region"], json.dumps(p), now) for p in picked],
    )
    conn.commit()
    return len(picked)


def next_unlabeled(conn: sqlite3.Connection) -> dict | None:
    ensure_schema(conn)
    row = conn.execute(
        "SELECT candidate FROM eval_items WHERE source_url NOT IN"
        " (SELECT source_url FROM eval_labels) ORDER BY sampled_at, source_url LIMIT 1"
    ).fetchone()
    return json.loads(row[0]) if row else None


def progress(conn: sqlite3.Connection) -> tuple[int, int]:
    ensure_schema(conn)
    total = conn.execute("SELECT COUNT(*) FROM eval_items").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM eval_labels").fetchone()[0]
    return done, total


def save_label(
    conn: sqlite3.Connection, source_url: str, is_real: bool | None, event_type: str,
    region: str, duplicate: bool, note: str = "", labeled_by: str = "author",
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO eval_labels VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (source_url, None if is_real is None else int(is_real), event_type, region,
         int(duplicate), int(is_real is None), note,
         datetime.now(UTC).isoformat(timespec="seconds"), labeled_by),
    )
    conn.commit()


@dataclass(frozen=True)
class EvalScore:
    run_id: str
    n: int
    real_accuracy: float | None
    type_accuracy: float | None
    region_accuracy: float | None
    noise_rejection: float | None
    # What the pipeline actually keeps (real, tracked type, in Region) vs what the labels say it
    # should keep. Precision: kept Events that are right (type included). Recall: right ones kept.
    keep_precision: float | None = None
    keep_recall: float | None = None


def _ratio(hits: int, total: int) -> float | None:
    return hits / total if total else None


def score(
    conn: sqlite3.Connection, cfg: Config, tax: Taxonomy, refiner: Refiner, fetch=None,
) -> EvalScore:
    """Score `refiner` on every confidently labeled item. Writes no Events."""
    ensure_schema(conn)
    tickers = [a.ticker for a in cfg.assets]
    system = system_prompt(tax, tickers)
    prompt_hash = hashlib.sha1(system.encode()).hexdigest()[:12]
    run_id = f"{refiner.model}-{prompt_hash}-{datetime.now(UTC):%Y%m%dT%H%M%S%f}"
    rows = conn.execute(
        "SELECT i.candidate, l.is_real_event, l.event_type, l.region FROM eval_items i"
        " JOIN eval_labels l USING (source_url) WHERE l.unsure = 0"
    ).fetchall()
    real_hits = type_hits = type_total = region_hits = noise_hits = noise_total = 0
    kept = kept_right = should = should_kept = 0
    kwargs = {"fetch": fetch} if fetch else {}
    for cand_json, is_real, label_type, label_region in rows:
        cand = json.loads(cand_json)
        article = fetch_article(cand["source_url"], cand["event_date"], **kwargs)
        result, usage = refiner.refine(system, user_prompt(cand, article))
        record_spend(conn, usage, "eval")
        pred_real = bool(result.is_real_event and result.event_type != "none")
        real_hits += pred_real == bool(is_real)
        region_hits += bool(result.in_region) == (label_region == cand["region"])
        keep = pred_real and bool(result.in_region)
        should_keep = bool(is_real) and label_region == cand["region"]
        kept += keep
        kept_right += keep and should_keep and result.event_type == label_type
        should += should_keep
        should_kept += keep and should_keep
        if is_real:
            type_total += 1
            type_hits += result.event_type == label_type
        else:
            noise_total += 1
            noise_hits += not pred_real
        conn.execute(
            "INSERT INTO eval_predictions (run_id, source_url, is_real, event_type, in_region)"
            " VALUES (?, ?, ?, ?, ?)",
            (run_id, cand["source_url"], int(pred_real), result.event_type,
             int(bool(result.in_region))))
    s = EvalScore(run_id, len(rows), _ratio(real_hits, len(rows)), _ratio(type_hits, type_total),
                  _ratio(region_hits, len(rows)), _ratio(noise_hits, noise_total),
                  _ratio(kept_right, kept), _ratio(should_kept, should))
    conn.execute(
        "INSERT INTO eval_runs (run_id, model, prompt_hash, taxonomy_version, n, real_accuracy,"
        " type_accuracy, region_accuracy, noise_rejection, created_at, keep_precision,"
        " keep_recall) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, refiner.model, prompt_hash, tax.version, s.n, s.real_accuracy, s.type_accuracy,
         s.region_accuracy, s.noise_rejection, datetime.now(UTC).isoformat(timespec="seconds"),
         s.keep_precision, s.keep_recall),
    )
    conn.commit()
    return s
