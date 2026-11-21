"""Independent audit of the Codex history refinement (ADR-0029).

Codex both labeled the Eval set and refined the history, so the Eval set can't tell whether Codex
itself is right (ADR-0027). This audit re-refines a random sample of Codex's decisions with a
different model family (Gemini via Antigravity CLI), blind to Codex's answer, and reports how
often the two agree on keep vs reject and on the Event type, with Cohen's kappa.

Agreement is not accuracy: two models can share a mistake. But low agreement would be a clear
warning, and every disagreement is stored for a human (or a judge model) to look at.
"""

from __future__ import annotations

import json
import random
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

from tremor.config import Config
from tremor.evalset import _predict
from tremor.refine import event_id_for, fetch_article, system_prompt, user_prompt
from tremor.taxonomy import Taxonomy

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_items (
  run_id TEXT NOT NULL, source_url TEXT NOT NULL, headline TEXT,
  codex_keep INTEGER NOT NULL, codex_type TEXT,
  check_keep INTEGER NOT NULL, check_type TEXT, check_reason TEXT,
  PRIMARY KEY (run_id, source_url)
);
CREATE TABLE IF NOT EXISTS audit_runs (
  run_id TEXT PRIMARY KEY, checker TEXT NOT NULL, refined_by TEXT NOT NULL, n INTEGER NOT NULL,
  keep_agreement REAL, kappa REAL, type_agreement REAL, created_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class AuditResult:
    run_id: str
    n: int
    keep_agreement: float
    kappa: float
    type_agreement: float | None
    both_keep: int
    only_codex: int
    only_checker: int
    neither: int


def kappa(a: list[bool], b: list[bool]) -> float:
    """Cohen's kappa for two binary raters: agreement beyond what chance would give."""
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def sample(conn: sqlite3.Connection, tax: Taxonomy, n: int, seed: int,
           queued_only: bool = False) -> list[dict]:
    """Half kept, half rejected (or as many as exist), from Candidates refined under `tax`.
    `queued_only`: only Candidates that came in through the Jev screen (ADR-0031): screened
    URLs that were refined. Uses jev_answers, not jev_queue, which is rebuilt on each pass."""
    conn.row_factory = sqlite3.Row
    extra = (" AND source_url IN (SELECT source_url FROM jev_answers WHERE kind = 'screen')"
             " AND source_url NOT IN (SELECT source_url FROM eval_items)") if queued_only else ""
    rows = [dict(r) for r in conn.execute(
        f"""SELECT source_url, MIN(event_date) AS event_date, candidate_types, region,
                  MAX(actor1) AS actor1, MAX(actor2) AS actor2, MAX(place) AS place,
                  AVG(lat) AS lat, AVG(lon) AS lon, SUM(num_articles) AS coverage,
                  MAX(status) AS status
           FROM candidates WHERE refined_tax = ? AND status IN ('refined', 'rejected'){extra}
           GROUP BY source_url ORDER BY source_url""", (tax.version,))]
    conn.row_factory = None
    rng = random.Random(seed)
    kept = [r for r in rows if r["status"] == "refined"]
    rej = [r for r in rows if r["status"] == "rejected"]
    k = min(len(kept), n // 2)
    return rng.sample(kept, k) + rng.sample(rej, min(len(rej), n - k))


def run(conn: sqlite3.Connection, cfg: Config, tax: Taxonomy, checker, n: int = 100,
        seed: int = 11, workers: int = 4, fetch=None, log=print,
        queued_only: bool = False) -> AuditResult:
    conn.executescript(SCHEMA)
    region = "red_sea"
    valid = {t.id for t in tax.event_types}
    system = system_prompt(tax, [a.ticker for a in cfg.assets], region)
    cands = sample(conn, tax, n, seed, queued_only)
    kw = {"fetch": fetch} if fetch else {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        arts = list(pool.map(lambda c: fetch_article(c["source_url"], c["event_date"], **kw),
                             cands))
    log(f"auditing {len(cands)} Codex decisions with {checker.model}…")
    preds = _predict(checker, system, [user_prompt(c, a) for c, a in zip(cands, arts)], workers)
    refined_by = conn.execute(
        "SELECT model FROM events WHERE taxonomy_version = ? AND origin = 'gdelt' "
        "GROUP BY model ORDER BY COUNT(*) DESC LIMIT 1", (tax.version,)).fetchone()
    run_id = f"audit-{checker.model}-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    a, b, type_pairs = [], [], []
    from tremor.refine import Usage, record_spend

    for _, u in preds:  # paid checkers (Claude) count against the daily cap like any refinement
        if isinstance(u, Usage) and u.usd:
            record_spend(conn, u, "audit")
    for cand, art, (res, _) in zip(cands, arts, preds):
        if isinstance(res, Exception):
            log(f"  skipped {cand['source_url']}: {res}")
            continue
        ev = conn.execute("SELECT event_type FROM events WHERE id = ?",
                          (event_id_for(cand["source_url"]),)).fetchone()
        codex_keep = cand["status"] == "refined" and ev is not None
        codex_type = ev[0] if ev else None
        check_keep = bool(res.is_real_event and res.event_type in valid and res.in_region)
        a.append(codex_keep)
        b.append(check_keep)
        if codex_keep and check_keep:
            type_pairs.append(codex_type == res.event_type)
        conn.execute(
            "INSERT INTO audit_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, cand["source_url"], art.title, int(codex_keep), codex_type,
             int(check_keep), res.event_type, res.noise_reason or res.summary))
    if not a:
        raise RuntimeError("the checker answered no items")
    agree = sum(x == y for x, y in zip(a, b)) / len(a)
    k = kappa(a, b)
    ta = sum(type_pairs) / len(type_pairs) if type_pairs else None
    conn.execute("INSERT INTO audit_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (run_id, checker.model, refined_by[0] if refined_by else "?", len(a), agree, k,
                  ta, datetime.now(UTC).isoformat(timespec="seconds")))
    conn.commit()
    return AuditResult(run_id, len(a), agree, k, ta,
                       sum(x and y for x, y in zip(a, b)), sum(x and not y for x, y in zip(a, b)),
                       sum(y and not x for x, y in zip(a, b)),
                       sum(not x and not y for x, y in zip(a, b)))


def disagreements(conn: sqlite3.Connection, run_id: str) -> list[tuple]:
    return conn.execute(
        "SELECT headline, codex_keep, codex_type, check_keep, check_type, check_reason, source_url"
        " FROM audit_items WHERE run_id = ? AND codex_keep != check_keep", (run_id,)).fetchall()


JUDGE_MODEL = "claude-opus-4-6-thinking"  # a third model family, also on the Antigravity plan


def judge(conn: sqlite3.Connection, tax: Taxonomy, run_id: str, runner=None,
          model: str = JUDGE_MODEL, fetch=None) -> list[dict]:
    """A third model rules on each keep/reject disagreement, seeing both answers.

    Stored in audit_items.judge_keep (1 keep, 0 reject, NULL not confident)."""
    from tremor.panel import rules, run_agy

    runner = runner or run_agy
    cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_items)")}
    for c in ("judge_keep INTEGER", "judge_reason TEXT"):
        if c.split()[0] not in cols:
            conn.execute(f"ALTER TABLE audit_items ADD COLUMN {c}")
    rows = conn.execute(
        "SELECT a.source_url, a.headline, a.codex_keep, a.codex_type, a.check_type,"
        " a.check_reason, e.summary, MIN(c.event_date)"
        " FROM audit_items a JOIN candidates c USING (source_url)"
        " LEFT JOIN events e ON e.source_url = a.source_url"
        " WHERE a.run_id = ? AND a.codex_keep != a.check_keep GROUP BY a.source_url",
        (run_id,)).fetchall()
    kw = {"fetch": fetch} if fetch else {}
    items = []
    for i, (url, head, ck, ctype, xtype, xreason, csum, day) in enumerate(rows):
        art = fetch_article(url, day, **kw)
        keeper = {"type": ctype, "summary": csum} if ck else {"type": xtype, "summary": xreason}
        rejecter = xreason if ck else "rejected (no in-Region event of a listed type)"
        items.append({"id": i, "headline": head, "date": day, "text": (art.text or "")[:8000],
                      "reviewer_A_keeps_as": keeper, "reviewer_B_rejects_because": rejecter})
    if not items:
        return []
    schema = {"type": "object", "additionalProperties": False, "required": ["rulings"],
              "properties": {"rulings": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False,
                  "required": ["id", "keep", "confident", "reason"],
                  "properties": {"id": {"type": "integer"}, "keep": {"type": "boolean"},
                                 "confident": {"type": "boolean"},
                                 "reason": {"type": "string"}}}}}}
    prompt = (f"You are the JUDGE between two reviewers.\n\n{rules(tax)}\n\nAn article is KEPT "
              "when it reports a real event of a listed type inside the Region. A roundup article "
              "that covers several stories counts if one of its stories is a real, new, in-Region "
              "event of a listed type that the article reports with enough detail to date it. "
              "For each item, reviewer A keeps it and reviewer B rejects it. Read the article and "
              "rule keep true or false. Set confident false if the article doesn't settle it.\n\n"
              "ITEMS:\n" + json.dumps(items, ensure_ascii=False))
    out = runner(prompt, schema, model)
    by_id = {r["id"]: r for r in out["rulings"]}
    results = []
    for i, (url, head, ck, *_rest) in enumerate(rows):
        r = by_id.get(i)
        keep = None if not r or not r["confident"] else int(r["keep"])
        conn.execute("UPDATE audit_items SET judge_keep = ?, judge_reason = ? "
                     "WHERE run_id = ? AND source_url = ?",
                     (keep, r["reason"] if r else "no ruling", run_id, url))
        results.append({"headline": head, "codex_keep": ck, "judge_keep": keep,
                        "reason": r["reason"] if r else "no ruling"})
    conn.commit()
    return results
