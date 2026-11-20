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
from concurrent.futures import ThreadPoolExecutor
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
    item_cols = {r[1] for r in conn.execute("PRAGMA table_info(eval_items)")}
    if "headline" not in item_cols:  # stored by the panel's article fetch, for story matching
        conn.execute("ALTER TABLE eval_items ADD COLUMN headline TEXT")
    if "split" not in item_cols:  # 'test' is scored; 'teach' supplies worked examples (ADR-0026)
        conn.execute("ALTER TABLE eval_items ADD COLUMN split TEXT NOT NULL DEFAULT 'test'")
    pred_cols = {r[1] for r in conn.execute("PRAGMA table_info(eval_predictions)")}
    if "in_region" not in pred_cols:
        conn.execute("ALTER TABLE eval_predictions ADD COLUMN in_region INTEGER")


def sample(conn: sqlite3.Connection, region: str, n: int = 100, seed: int = 7,
           split: str = "test") -> int:
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
        "INSERT OR IGNORE INTO eval_items (source_url, event_date, region, candidate, sampled_at,"
        " split) VALUES (?, ?, ?, ?, ?, ?)",
        [(p["source_url"], p["event_date"], p["region"], json.dumps(p), now, split)
         for p in picked],
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


def has_author_label(conn: sqlite3.Connection, source_url: str) -> bool:
    row = conn.execute("SELECT labeled_by FROM eval_labels WHERE source_url = ?",
                       (source_url,)).fetchone()
    return bool(row) and row[0] == "author"


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


def _predict(refiner, system: str, prompts: list[str], workers: int) -> list[tuple]:
    """(result, usage) per prompt, in order; batched and parallel when the refiner supports it.
    A failed item comes back as (exception, None) and is left out of the score."""
    def one(p):
        try:
            return refiner.refine(system, p)
        except Exception as e:
            if getattr(e, "fatal", False):
                raise
            return e, None

    size = getattr(refiner, "batch_size", 0)
    if not size:
        return [one(p) for p in prompts]
    chunks = [prompts[i:i + size] for i in range(0, len(prompts), size)]

    def batch(ch):
        try:
            return refiner.refine_batch(system, ch)
        except Exception as e:
            if getattr(e, "fatal", False):
                raise
            return [(e, None)] * len(ch)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [r for out in pool.map(batch, chunks) for r in out]


def score(
    conn: sqlite3.Connection, cfg: Config, tax: Taxonomy, refiner: Refiner, fetch=None,
    workers: int = 4,
) -> EvalScore:
    """Score `refiner` on every confidently labeled item. Writes no Events."""
    ensure_schema(conn)
    tickers = [a.ticker for a in cfg.assets]
    system = system_prompt(tax, tickers)
    prompt_hash = hashlib.sha1(system.encode()).hexdigest()[:12]
    run_id = f"{refiner.model}-{prompt_hash}-{datetime.now(UTC):%Y%m%dT%H%M%S%f}"
    rows = conn.execute(
        "SELECT i.candidate, l.is_real_event, l.event_type, l.region FROM eval_items i"
        " JOIN eval_labels l USING (source_url) WHERE l.unsure = 0 AND i.split = 'test'"
    ).fetchall()
    valid_types = {t.id for t in tax.event_types}
    real_hits = type_hits = type_total = region_hits = noise_hits = noise_total = 0
    kept = kept_right = should = should_kept = 0
    kwargs = {"fetch": fetch} if fetch else {}
    cands = [json.loads(r[0]) for r in rows]
    with ThreadPoolExecutor(max_workers=16) as pool:
        articles = list(pool.map(
            lambda c: fetch_article(c["source_url"], c["event_date"], **kwargs), cands))
    prompts = [user_prompt(c, a) for c, a in zip(cands, articles)]
    preds = _predict(refiner, system, prompts, workers)
    scored = 0
    for (cand_json, is_real, label_type, label_region), cand, (result, usage) in zip(
            rows, cands, preds):
        if isinstance(result, Exception):
            print(f"  skipped {cand['source_url']}: {result}")
            continue
        scored += 1
        record_spend(conn, usage, "eval")
        # Same keep predicate as refinement: real, a taxonomy id, and (for keeping) in Region.
        pred_real = bool(result.is_real_event and result.event_type in valid_types)
        real_hits += pred_real == bool(is_real)
        region_hits += bool(result.in_region) == (label_region == cand["region"])
        keep = pred_real and bool(result.in_region)
        should_keep = bool(is_real) and label_region == cand["region"]
        kept += keep
        kept_right += keep and should_keep and result.event_type == label_type
        should += should_keep
        should_kept += keep and should_keep and result.event_type == label_type
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
        conn.commit()  # never hold the write lock across slow article fetches and LLM calls
    s = EvalScore(run_id, scored, _ratio(real_hits, scored), _ratio(type_hits, type_total),
                  _ratio(region_hits, scored), _ratio(noise_hits, noise_total),
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


def score_jev(conn: sqlite3.Connection, tax: Taxonomy, judge=None, fetch=None,
              workers: int = 8, split: str = "test") -> dict:
    """Jev pre-filter experiment on the test split: raw probabilities per item, then keep
    precision/recall at several thresholds, and how much a pre-filter would forward."""
    from tremor import jev

    rows = conn.execute(
        "SELECT i.candidate, l.is_real_event, l.event_type, l.region FROM eval_items i"
        " JOIN eval_labels l USING (source_url) WHERE l.unsure = 0 AND i.split = ?", (split,)
    ).fetchall()
    kwargs = {"fetch": fetch} if fetch else {}
    cands = [json.loads(r[0]) for r in rows]
    with ThreadPoolExecutor(max_workers=16) as pool:
        arts = list(pool.map(
            lambda c: fetch_article(c["source_url"], c["event_date"], **kwargs), cands))
    judgments = (judge or jev.ask_many)([(a.title, a.text) for a in arts], workers=workers)
    items = []
    for (_, is_real, label_type, label_region), cand, j in zip(rows, cands, judgments):
        if isinstance(j, Exception):
            print(f"  skipped {cand['source_url']}: {j}")
            continue
        items.append({"url": cand["source_url"], "probs": j.probs, "model": j.model,
                      "tokens": j.input_tokens,
                      "should_keep": bool(is_real) and label_region == cand["region"],
                      "label_type": label_type})
    out = {"n": len(items), "tokens": sum(i["tokens"] for i in items), "items": items,
           "keep": {}, "prefilter": {}}
    for yes in (0.5, 0.6, 0.7, 0.8):
        kept = right = should = caught = 0
        for it in items:
            keep, kind = jev.decide(it["probs"], yes)
            ok = it["should_keep"] and kind == it["label_type"]
            kept += keep
            right += keep and ok
            should += it["should_keep"]
            caught += keep and ok
        out["keep"][yes] = {"precision": _ratio(right, kept), "recall": _ratio(caught, should),
                            "kept": kept}
    for low in (0.05, 0.1, 0.2, 0.3):
        fwd = [it for it in items if jev.pass_on(it["probs"], low)]
        should = [it for it in items if it["should_keep"]]
        out["prefilter"][low] = {
            "forwarded": _ratio(len(fwd), len(items)),
            "keeps_forwarded": _ratio(sum(it["should_keep"] for it in fwd), len(should))}
    return out
