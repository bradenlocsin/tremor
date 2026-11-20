# Glossary

## TREMOR

Tracking Risk Events & Market Outcome Reactions. A finance product that turns geopolitical Events into market-relevant insight about Assets. Geopolitics and Sensor data are the inputs; financial understanding is the output (ADR-0003).

_Avoid_: "GAIA", the project's former name (ADR-0024).

## Event

The core unit of TREMOR. Something that happened at a place and time, involving Actors, linked to nearby Sensor data and to the Assets it may move. Example: a strike on a tanker in the Red Sea, linked to vessel tracks, the Bab-el-Mandeb chokepoint, Brent crude and container freight rates.

## Event type

A category from TREMOR's curated taxonomy of about 10–15 market-relevant types (e.g. shipping attack, sanctions imposed, military strike, export ban, election shock, chokepoint closure). The LLM assigns it during refinement (ADR-0011).

## Region

A predefined geopolitical zone (e.g. Red Sea / Bab-el-Mandeb, Strait of Hormuz, Taiwan Strait, Black Sea).

## Comparables

The past Events used in an Event's event study: same Event type and Region, with a minimum N of 8. With fewer, broaden to Event type only and disclose it (ADR-0011).

_Avoid_: "similar events" in code or UI copy. Use Comparables.

## Episode

A burst of Events with the same Event type and Region, each within 10 trading days of the previous one. Only the first Event of an Episode counts as a Comparable. Later ones are grouped under it in the Event feed (ADR-0020).

_Avoid_: "Theater", an earlier informal idea that Episode replaces.

## Event feed

The live, most-recent-first list of refined Events on the dashboard's main screen (ADR-0009).

## Candidate

A raw, unrefined event record from GDELT. It becomes an Event only after LLM refinement (ADR-0007).

_Avoid_: calling a Candidate an "Event". It may be noise or a duplicate.

## Fidelity

How an Event was refined: **full** (from the live article or a Wayback Machine snapshot) or **lower** (from GDELT fields plus the headline only). Comparables made up mostly of lower-Fidelity Events cap Confidence at Med (ADR-0017).

## Actor

A participant in an Event: a state, an armed group, a company or a leader.

## Sensor data

Live physical observations TREMOR gets from gods-eye-view: aircraft, vessels, satellites, fires, earthquakes, cyclones, cameras, infrastructure and military installations. TREMOR does not collect sensor data itself (see ADR-0001). In v1 it is context only, never used in Analysis, except that a daily job records chokepoint vessel counts to build history (ADR-0023).

_Avoid_: "feeds" or "layers" when you mean sensor data in general.

## Claim

Any assertion TREMOR stores, such as "X happened", "A is allied with B" or "this event affects Brent crude". Every Claim carries Provenance (ADR-0002).

## Provenance

The Source of a Claim plus a timestamp of when it was observed or reported. Required on every Claim.

## Source

Where a Claim came from: a gods-eye-view sensor reading, a news article, a government statement, the user's own judgment, and so on.

## Asset

A tradable thing TREMOR can link a Claim to. In practice, a member of the Asset universe.

## Asset universe

The curated set of about 30–50 liquid, geopolitically sensitive ETFs TREMOR covers, with free daily price history. It covers commodities through ETFs (oil, natural gas, gold, grains), sectors (defense, energy, shipping as a freight proxy, semiconductors), and regions, FX and safe havens (country ETFs, the dollar, Treasuries). The first build may use a 5-Asset subset (oil, gold, defense, shipping, the dollar).

## Analysis

TREMOR's always-on output: evidence of how Events have affected or may affect Assets. Example: "past Red Sea disruptions moved freight rates +X% over Y days."

## Event study

The quant method behind Analysis: take past Events similar to the current one and measure how the linked Assets moved over a window afterward (ADR-0006).

## Abnormal return (AR)

An Asset's actual return minus the return a market model (vs. SPY) expected. The part of a move that the overall market doesn't explain (ADR-0010).

_Avoid_: "impact" or "move" when you mean AR specifically.

## CAR

Cumulative abnormal return: AR summed over the event window (day −1 to +20). The y-axis of the event-study chart.

## Recommendation

A view on an Asset: a Stance (Overweight / Underweight), a horizon (5 or 20 trading days) and a Confidence (Low / Med / High), plus an LLM-written rationale. It exists only when CAR is significant. Stance and horizon come from the numbers. The LLM may only downgrade Confidence (ADR-0012). It always cites the Analysis it rests on. It is a separate layer that can be switched off (ADR-0004). In v1, Recommendations are generic: impersonal and the same for every viewer (ADR-0008).

_Avoid_: "signal" when you mean a Recommendation. A signal should only mean an input, not a verdict. Avoid "buy/sell" in UI copy; use Overweight / Underweight.

## Eval set

About 100 Candidates labeled blind (real vs. noise, Event type, Region). Labeled by a Codex model panel of labeler, skeptic and judge, which the author can override by hand (ADR-0025). Used to score LLM refinement on every prompt or model change (ADR-0019).

## Audit

A blind re-check of a random sample of the history refinement by a second model family (Gemini, via Antigravity CLI). It reports how often the two models agree on keep vs. reject, with Cohen's kappa. Agreement is not accuracy, but low agreement is a warning (ADR-0029).

## Shock

An Event used as an independent case in the pre-registered feature tests: the first Event of its series at least 5 trading days after the previous one, so +5-day windows don't overlap (ADR-0031).

## Track record

TREMOR's scored history of Recommendations: back-tested over historical Events without look-ahead, plus live Recommendations once their horizon passes (ADR-0018).

## Look-ahead bias

Using information from after an Event's date when producing its historical Recommendation. Forbidden in the back-test: Comparables must come before the Event.

## Stance

A Recommendation's direction: Overweight (expect positive CAR) or Underweight (expect negative CAR).

## Confidence

Low / Med / High, computed from N, effect size and whether the Comparables were broadened. The LLM may lower it, never raise it.

## Viewer

Anyone who has entered the passcode in v1. All Viewers see the same Analysis and generic Recommendations (ADR-0008).

## Passcode gate

v1's only access control: one shared passcode protects the whole site. It is not a user account system.

## User

_(Deferred past v1.)_ A logged-in person with their own account and Portfolio (ADR-0005).

## Portfolio

_(Deferred past v1, ADR-0008.)_ A User's holdings, mapped onto the Asset universe so Recommendations can be personalized. The intended path is manual entry and CSV import first, brokerage linking later.

## License tag

A label on every Source: commercial-OK or non-commercial. Everything is usable personally; the tag exists so a future paid version can filter (ADR-0004).

## q-value

A p-value adjusted for running many tests at once (Benjamini–Hochberg). Each Analysis tests every Asset at +5 and +20 trading days, so a Recommendation needs q < 0.05, not just p < 0.05 (ADR-0028).

## Placebo test

The same event study run on random dates when nothing happened. It shows how often chance alone looks "significant", and how unusual the real result is by comparison (ADR-0028).
