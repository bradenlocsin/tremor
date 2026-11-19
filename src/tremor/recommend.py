"""Recommendations: the numbers decide, the LLM explains (ADR-0004, ADR-0008, ADR-0012).

Deterministic part (reproducible from the Analysis):
  * exists only if CAR is significant at +5 or +20 trading days (and N >= the minimum)
  * horizon = the significant window with the larger |t|; Stance = sign of that CAR
  * Confidence from N, |t| and effect size; capped at Med when the Comparables were broadened
    beyond the Region or most of them are lower Fidelity (ADR-0011, ADR-0017)

LLM part: a rationale citing the Analysis. It may lower Confidence (with a stored reason),
never raise it or flip the Stance.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from tremor.analysis import Analysis
from tremor.event_study import StudyResult
from tremor.events import Event
from tremor.refine import SPEND_SCHEMA, Usage, record_spend

LEVELS = ("Low", "Med", "High")
HORIZONS = (5, 20)
DISCLAIMER = "Not financial advice. Educational analysis of historical market reactions."

SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendations (
    id                   TEXT PRIMARY KEY,   -- target Event id + Asset
    event_id             TEXT NOT NULL,
    episode_id           TEXT,
    asset                TEXT NOT NULL,
    stance               TEXT,               -- Overweight | Underweight | NULL (no Recommendation)
    horizon_days         INTEGER,
    mean_car             REAL,
    t_stat               REAL,
    p_value              REAL,
    n                    INTEGER NOT NULL,
    broadened            INTEGER NOT NULL,
    confidence_computed  TEXT,
    confidence           TEXT,
    downgrade_reason     TEXT,
    rationale            TEXT,
    no_rec_reason        TEXT,
    comparables          TEXT,               -- comma-separated Event ids (citation)
    model                TEXT,
    created_at           TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Recommendation:
    event_id: str
    asset: str
    n: int
    broadened: bool
    comparables: tuple[str, ...]
    episode_id: str | None = None
    stance: str | None = None
    horizon_days: int | None = None
    mean_car: float | None = None
    t_stat: float | None = None
    p_value: float | None = None
    confidence_computed: str | None = None
    confidence: str | None = None
    downgrade_reason: str | None = None
    rationale: str | None = None
    no_rec_reason: str | None = None
    model: str | None = None

    @property
    def exists(self) -> bool:
        return self.stance is not None


# ---------------------------------------------------------------- deterministic part


def compute_confidence(n: int, t: float, car: float, broadened: bool, mostly_lower: bool) -> str:
    score = 0
    score += 1 if n >= 15 else 0
    score += 1 if abs(t) >= 3 else 0
    score += 1 if abs(car) >= 0.02 else 0
    score -= 1 if broadened else 0
    level = "High" if score >= 2 else "Med" if score == 1 else "Low"
    if (mostly_lower or broadened) and level == "High":
        level = "Med"  # weaker evidence can't reach High
    return level


def decide(
    target: Event, asset: str, result: StudyResult, fidelity: dict[str, str],
    episode_id: str | None = None,
) -> Recommendation:
    base = Recommendation(
        event_id=target.id, asset=asset, n=result.n, broadened=result.broadened,
        comparables=result.event_ids, episode_id=episode_id,
    )
    if result.insufficient:
        return replace(base, no_rec_reason=f"only {result.n} usable Comparables (minimum 8)")
    sig = [result.headlines[d] for d in HORIZONS if d in result.headlines
           and result.headlines[d].significant]
    if not sig:
        return replace(base, no_rec_reason="historical effect not distinguishable from noise")
    best = max(sig, key=lambda h: abs(h.t_stat))
    lower = sum(fidelity.get(e) == "lower" for e in result.event_ids)
    level = compute_confidence(result.n, best.t_stat, best.mean_car, result.broadened,
                               mostly_lower=lower > result.n / 2)
    return replace(
        base,
        stance="Overweight" if best.mean_car > 0 else "Underweight",
        horizon_days=best.day,
        mean_car=best.mean_car,
        t_stat=best.t_stat,
        p_value=best.p_value,
        confidence_computed=level,
        confidence=level,
    )


# ---------------------------------------------------------------- LLM part


class Rationale(BaseModel):
    rationale: str = Field(description="3-5 sentences. Cite N, the CAR and the horizon given. "
                           "Say how this Event resembles its Comparables and what is different.")
    downgrade_to: Literal["Low", "Med"] | None = Field(
        default=None, description="Lower Confidence only if this Event clearly differs from its "
        "Comparables in a way that weakens the historical pattern. Otherwise null.")
    downgrade_reason: str | None = None


class Explainer(Protocol):
    model: str

    def explain(self, system: str, prompt: str) -> tuple[Rationale, Usage]: ...


class ClaudeExplainer:
    def __init__(self, model: str):
        import anthropic

        self.model = model
        self.client = anthropic.Anthropic()

    def explain(self, system: str, prompt: str) -> tuple[Rationale, Usage]:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=4000,
            output_config={"effort": "medium"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=Rationale,
        )
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise RuntimeError(f"rationale returned no structured output ({response.stop_reason})")
        u = response.usage
        return response.parsed_output, Usage(self.model, u.input_tokens, u.output_tokens)


class FakeExplainer:
    model = "fake"

    def explain(self, system: str, prompt: str) -> tuple[Rationale, Usage]:
        return Rationale(rationale="(template rationale) " + prompt.splitlines()[0]), Usage(
            "fake", 0, 0)


SYSTEM = f"""You explain a market-analysis tool's Recommendation to an investor.
The Stance, horizon and statistics were computed from an event study and are final: never
contradict them, never invent numbers, and never recommend a different position. Write plainly,
cite the numbers you are given, and say what differs between this Event and its historical
Comparables. You may lower the Confidence only for a concrete, stated reason. {DISCLAIMER}"""


def explain_prompt(target: Event, rec: Recommendation, comparable_titles: list[str],
                   context: str = "") -> str:
    car = f"{rec.mean_car * 100:+.2f}%"
    lines = [
        f"{rec.stance} {rec.asset} over {rec.horizon_days} trading days "
        f"(Confidence {rec.confidence_computed}).",
        f"Event ({target.occurred_on}): {target.title}. {target.summary or ''}",
        f"Evidence: average CAR {car} at +{rec.horizon_days} days across N={rec.n} "
        f"Comparables (t={rec.t_stat:.2f}, p={rec.p_value:.3f})"
        + (", broadened to Event type only" if rec.broadened else "") + ".",
        "Comparables: " + "; ".join(comparable_titles[:15]),
    ]
    if context:
        lines.append(f"Current context: {context}")
    return "\n".join(lines)


def apply_rationale(rec: Recommendation, r: Rationale, model: str) -> Recommendation:
    """Attach the rationale; accept a downgrade only if it actually lowers Confidence."""
    out = replace(rec, rationale=r.rationale, model=model)
    if r.downgrade_to and LEVELS.index(r.downgrade_to) < LEVELS.index(rec.confidence_computed):
        out = replace(out, confidence=r.downgrade_to,
                      downgrade_reason=r.downgrade_reason or "unspecified")
    return out


# ---------------------------------------------------------------- orchestration


def recommend(
    analysis: Analysis, events_by_id: dict[str, Event], explainer: Explainer | None,
    conn: sqlite3.Connection | None = None, context: str = "",
) -> list[Recommendation]:
    target = analysis.target
    fidelity = {k: e.fidelity for k, e in events_by_id.items()}
    ep_id = analysis.episode.id if analysis.episode else None
    recs = []
    for asset, result in analysis.results.items():
        rec = decide(target, asset, result, fidelity, ep_id)
        if rec.exists and explainer is not None:
            titles = [events_by_id[e].title for e in rec.comparables if e in events_by_id]
            r, usage = explainer.explain(SYSTEM, explain_prompt(target, rec, titles, context))
            if conn is not None:
                conn.executescript(SPEND_SCHEMA)
                record_spend(conn, usage, "rationale")
            rec = apply_rationale(rec, r, usage.model)
        recs.append(rec)
    return recs


def save_recommendations(conn: sqlite3.Connection, recs: list[Recommendation]) -> None:
    conn.executescript(SCHEMA)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.executemany(
        "INSERT OR REPLACE INTO recommendations VALUES"
        " (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (f"{r.event_id}:{r.asset}", r.event_id, r.episode_id, r.asset, r.stance,
             r.horizon_days, r.mean_car, r.t_stat, r.p_value, r.n, int(r.broadened),
             r.confidence_computed, r.confidence, r.downgrade_reason, r.rationale,
             r.no_rec_reason, ",".join(r.comparables), r.model, now)
            for r in recs
        ],
    )
    conn.commit()
