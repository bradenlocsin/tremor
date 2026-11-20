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
