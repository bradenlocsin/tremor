# 31. Pre-registered shock features (Jev) and a full-pool headline screen

Date: 2026-11-19
Status: Accepted. Written before any feature has been compared with returns.

## Context

The event study counts only the first Event of each Episode (ADR-0020). A year-long campaign is one Comparable, and an intercepted drone counts the same as a burning tanker. Meanwhile the backfill refines only the 3 most-covered articles per day and Event type, about 10,500 of 170,467 Red Sea Candidates. The first report of an incident often has low coverage, so day 0 can land late, and a late day 0 understates the reaction.

Jev (ADR-0030) answers typed yes/no questions for about $0.00005 per article. That makes two things cheap: describing every Event, and screening the whole Candidate pool.

## Decision 1: features, fixed now

Jev answers these Nouls for every Event, from the article alone. Answers are stored in `jev_answers` (kind `features`). An answer counts as yes at ≥ 0.7, no at ≤ 0.3, and is left out in between.

| Feature | Question (abridged) |
|---|---|
| `vessel_damaged` | A ship was damaged, set on fire, sunk, or its crew hurt (not only intercepted or missed) |
| `energy_target` | The target was an oil or gas tanker, or energy infrastructure |
| `fatalities` | People were killed |
| `escalation` | The article presents it as a first or an expansion: a new kind of target, weapon, area or declared campaign |

## Decision 2: hypotheses, fixed now

The unit is a **shock**: an Event of the given type whose day 0 is at least 5 trading days after the previous shock in the same series. This thins each series, so the +5-day windows don't overlap. Each hypothesis compares the mean CAR of two shock series with Welch's t-test. Shocks are built separately within each group.

| # | Hypothesis | Asset(s) | Days |
|---|---|---|---|
| H1 | Shipping attacks with `vessel_damaged` move more than those without | BNO, BDRY | +5, +20 |
| H2 | Shipping attacks on an `energy_target` move oil more than other shipping attacks | BNO | +5, +20 |
| H3 | `escalation` Events of any first-slice type move more than non-escalation Events (absolute CAR) | BNO, GLD, ITA, BDRY, UUP | +5 |

These form one family of 11 tests (H1 4, H2 2, H3 5), corrected with Benjamini–Hochberg at q < 0.05. `fatalities` is descriptive only. Anything beyond this table is exploratory and reported as such.

Known limits:
- +20-day windows can overlap within a series.
- Comparing shocks within one Region shares market regimes.
- Results are run once, when the history backfill is complete, and reported whatever they show.

## Decision 3: headline screen of the whole pool

Jev screens every Candidate URL from its headline (taken from the URL) and GDELT fields, with no article fetch. It reuses the `incident`, type and `in_region` questions, and stores answers as `jev_answers` (kind `screen`). A Candidate that passes the screen joins the refinement queue even if it is outside the top 3 per day. The threshold is chosen on the teach split and reported on the test split before the full run.
