"""Jev (TypeSafe System One) as a cheap pre-filter for refinement: experiment (issue: Jev triage).

Jev makes small, literal judgments about one article with calibrated probabilities; code makes
the keep/reject decision from them (a truth table, not a prompt). All question wording lives here.

The idea under test: ask Jev about every Candidate for a fraction of a cent, and send only the
likely Events to the LLM refiner, so the hourly job can check more articles for the same spend.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from typesafe_sdk import Noul, TypeSafeClient

MODEL = "jev-1.14.0"  # pinned: thresholds are tuned against one version
MAX_CHARS = 6_000

# The Red Sea box (lat 10.5-22.5, lon 37.5-51.5) in words: Jev is weak with coordinates.
REGION = ("the Red Sea south of Jeddah, the Bab el-Mandeb strait and the Gulf of Aden, and on land: "
          "Yemen, Djibouti, Eritrea, northern Somalia (Somaliland and Puntland), and southwestern "
          "Saudi Arabia (Jizan, Najran, Asir and the Red Sea coast up to Jeddah)")

INCIDENT = {"true": "The article describes something that happened, such as a missile hitting a "
                    "tanker on Tuesday, an air strike on a port, or a group announcing it has "
                    "closed a strait.",
            "false": "The article is opinion, analysis, a forecast, an explainer, or a threat or "
                     "warning where no action was taken."}

QUESTIONS = {
    "incident": Noul(instructions="Does `article` report a specific incident that took place?",
                     criteria=INCIDENT),
    "main_news": Noul(
        instructions="Is a new incident the main news that `article` reports?",
        criteria={"true": "The article is mainly about something that just happened, such as "
                          "today's missile attack on a ship.",
                  "false": "Incidents appear only as background or history, for example a "
                           "blockade described as in place since last year, or an attack "
                           "mentioned in a story about a visit, a threat, port finances or "
                           "politics."}),
    "ship_attacked": Noul(
        instructions="Does `article` report that a ship or boat was struck, seized, boarded, "
                     "fired on, or targeted by missiles or drones?",
        criteria={"false": "No vessel was attacked, for example the article is about strikes on "
                           "land, about shipping rates, or about a navy destroying an armed "
                           "group's own boats (that is a military strike)."}),
    "land_strike": Noul(
        instructions="Does `article` report a missile, air, drone or artillery strike on a "
                     "target on land, or on an armed group's own boats, launch sites or weapons?",
        criteria={"false": "No strike on land is reported, for example only ground fighting, "
                           "a bombing by a militant, or an attack on a ship."}),
    "blockade": Noul(
        instructions="Does `article` report that a group announced or enforced a blockade, "
                     "closure or ban on ships passing through a strait or sea?"),
    "in_region": Noul(
        instructions="Did an incident reported in `article` take place in the area described "
                     "in `region`?",
        criteria={"false": "Every incident in the article happened elsewhere, for example in "
                           "the Strait of Hormuz, the Persian Gulf, Gaza, Israel or Sudan."}),
}

TYPE_OF = {"ship_attacked": "shipping_attack", "land_strike": "military_strike",
           "blockade": "chokepoint_disruption"}


@dataclass(frozen=True)
class Judgment:
    probs: dict[str, float]
    model: str
    input_tokens: int


def ask(client: TypeSafeClient, headline: str, text: str) -> Judgment:
    state = {"article": {"headline": headline or "", "text": (text or "")[:MAX_CHARS]},
             "region": REGION}
    r = client.system_one(state, QUESTIONS, model=MODEL)
    probs = {k: float(r.answers[k].noul) for k in QUESTIONS}
    tokens = int(getattr(r.usage, "input_tokens", 0) or 0)
    return Judgment(probs, r.model, tokens)


def decide(p: dict[str, float], yes: float = 0.7) -> tuple[bool, str]:
    """The truth table: keep when Jev says incident, in Region, and some tracked type."""
    kind = max(TYPE_OF, key=lambda k: p[k])
    keep = (p["incident"] >= yes and p.get("main_news", 1.0) >= yes
            and p["in_region"] >= yes and p[kind] >= yes)
    return keep, TYPE_OF[kind] if p[kind] >= yes else "none"


def pass_on(p: dict[str, float], low: float = 0.3) -> bool:
    """Pre-filter rule: forward to the LLM unless Jev is fairly sure it's not a keep."""
    kind = max(TYPE_OF, key=lambda k: p[k])
    return min(p["incident"], p.get("main_news", 1.0), p["in_region"], p[kind]) >= low


def ask_many(items: list[tuple[str, str]], workers: int = 8,
             client_factory: Callable[[], TypeSafeClient] = TypeSafeClient) -> list:
    """(headline, text) pairs -> Judgment or Exception per item, in order."""
    client = client_factory()

    def one(item):
        try:
            return ask(client, *item)
        except Exception as e:  # noqa: BLE001 - a failed call is an error, never a "no"
            return e

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, items))


# ---------------------------------------------------------------- pre-registered features (ADR-0031)

FEATURES = {
    "vessel_damaged": Noul(
        instructions="Does `article` report that a ship was damaged, set on fire, sunk, or that "
                     "its crew was hurt?",
        criteria={"false": "No ship was harmed, for example the missiles or drones were "
                           "intercepted or missed, or no ship was involved."}),
    "energy_target": Noul(
        instructions="Was the target of the incident in `article` an oil or gas tanker, or "
                     "energy infrastructure such as a refinery, pipeline or oil terminal?"),
    "fatalities": Noul(instructions="Does `article` report that people were killed?"),
    "escalation": Noul(
        instructions="Does `article` present the incident as a first or an expansion, such as a "
                     "new kind of target, a new weapon, a new area, or a newly declared campaign?",
        criteria={"false": "The incident is described as one more in an ongoing series of "
                           "similar attacks."}),
}
YES, NO = 0.7, 0.3


def flag(p: float) -> bool | None:
    """Pre-registered reading: yes at >= 0.7, no at <= 0.3, otherwise left out."""
    return True if p >= YES else False if p <= NO else None


# ---------------------------------------------------------------- storage (resumable runs)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jev_answers (
  source_url TEXT NOT NULL, kind TEXT NOT NULL, model TEXT NOT NULL, probs TEXT NOT NULL,
  input_tokens INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (source_url, kind)
);
"""


def save(conn, url: str, kind: str, j: Judgment) -> None:
    import json
    from datetime import UTC, datetime

    conn.execute("INSERT OR REPLACE INTO jev_answers VALUES (?, ?, ?, ?, ?, ?)",
                 (url, kind, j.model, json.dumps(j.probs), j.input_tokens,
                  datetime.now(UTC).isoformat(timespec="seconds")))


def answers(conn, kind: str) -> dict[str, dict[str, float]]:
    import json

    conn.executescript(SCHEMA)
    return {u: json.loads(p) for u, p in
            conn.execute("SELECT source_url, probs FROM jev_answers WHERE kind = ?", (kind,))}


def _ask(client, state: dict, questions: dict) -> Judgment:
    r = client.system_one(state, questions, model=MODEL)
    return Judgment({k: float(r.answers[k].noul) for k in questions}, r.model,
                    int(getattr(r.usage, "input_tokens", 0) or 0))


def screen_state(cand: dict) -> dict:
    """Headline-only state for the full-pool screen: no article fetch."""
    from tremor.refine import headline_from_url

    actors = [a for a in (cand.get("actor1"), cand.get("actor2")) if a]
    return {"article": {"headline": headline_from_url(cand["source_url"]),
                        "actors_named": actors, "place_named": cand.get("place") or ""},
            "region": REGION}


SCREEN = {k: QUESTIONS[k] for k in ("incident", "ship_attacked", "land_strike", "blockade",
                                    "in_region")}


def run(conn, kind: str, todo: list[tuple[str, dict]], workers: int = 16, log=print,
        client_factory: Callable[[], TypeSafeClient] = TypeSafeClient) -> dict:
    """Ask `kind` questions ('screen' or 'features') for each (url, state); commits as it goes.
    Stops on an auth or quota error rather than recording failures as answers."""
    conn.executescript(SCHEMA)
    questions = SCREEN if kind == "screen" else FEATURES
    client = client_factory()
    stats = {"done": 0, "errors": 0, "tokens": 0}

    def one(item):
        url, state = item
        try:
            return url, _ask(client, state, questions)
        except Exception as e:  # noqa: BLE001 - recorded as an error, never as an answer
            return url, e

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (url, j) in enumerate(pool.map(one, todo), 1):
            if isinstance(j, Exception):
                stats["errors"] += 1
                if stats["errors"] <= 3:
                    log(f"  {url}: {j}")
                if stats["errors"] >= 50 and stats["done"] == 0:
                    raise RuntimeError(f"Jev keeps failing: {j}")
                continue
            save(conn, url, kind, j)
            stats["done"] += 1
            stats["tokens"] += j.input_tokens
            if i % 500 == 0:
                conn.commit()
                log(f"  {i}/{len(todo)}  ({stats['tokens'] * 0.042 / 1e6:.3f} USD so far)")
    conn.commit()
    return stats


def episode_start_candidates(conn, calendar, gap: int, low: float = 0.2) -> list[str]:
    """Screened, not-yet-refined Candidate URLs that would become an Episode start if real.

    A Candidate qualifies when Jev's screen passes it at `low` and no Event of its likely type
    falls in the `gap` trading days before its date: it would then open a new Episode or move an
    existing Episode's day 0 earlier. Refining anything else only adds Events inside existing
    Episodes, which changes no Comparable (ADR-0031)."""
    import bisect

    import pandas as pd

    screened = answers(conn, "screen")
    days = list(pd.DatetimeIndex(calendar).normalize())
    pos = {d.date(): i for i, d in enumerate(days)}

    def tday(d) -> int:
        return bisect.bisect_left(days, pd.Timestamp(d))

    by_type: dict[str, list[int]] = {}
    for t, d in conn.execute("SELECT event_type, occurred_on FROM events WHERE region = 'red_sea'"):
        by_type.setdefault(t, []).append(tday(d))
    for v in by_type.values():
        v.sort()
    rows = conn.execute(
        "SELECT source_url, MIN(event_date) FROM candidates WHERE region = 'red_sea' AND"
        " status = 'new' AND source_url IN (SELECT source_url FROM jev_answers WHERE kind ="
        " 'screen') GROUP BY source_url").fetchall()
    out = []
    for url, d in rows:
        p = screened[url]
        if not pass_on(p, low):
            continue
        kind = TYPE_OF[max(TYPE_OF, key=lambda k: p[k])]
        t = pos.get(pd.Timestamp(d).date(), tday(d))
        prior = by_type.get(kind, [])
        i = bisect.bisect_left(prior, t)  # Events strictly before day t
        if i == 0 or t - prior[i - 1] > gap:
            out.append(url)
    return out
