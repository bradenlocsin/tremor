# 33. One exploratory paper-trading rule: long ITA after a corroborated military strike

Date: 2026-11-21
Status: Accepted (exploratory)

## Context

The ADR-0032 search promoted no rule: the best of 6,720, long ITA for 2 days after a military
strike Episode starts (+0.92% per trade after costs, 73% winners, t = 3.6, 22 trades), is what
the luckiest of that many random rules would show. So it is not a finding. It is economically
sensible, though (defense names rise after strikes), and it held across 1, 2, 5 and 10-day
holds. Paper trading it costs nothing and builds a record on news no model was trained on.

## Decision

- Paper-trade `start:military_strike#2 | ITA | 2 days | long`, labeled **exploratory**
  everywhere it is shown. It is not a holdout-confirmed rule, and the locked holdout year
  (ADR-0032) stays unused.
- `#2` is a false-alarm guard for the live feed (Haiku's precision is about 81–85%): at least
  two separate articles must report Events of the type in the Episode's first 2 days, and the
  signal counts from the day the second was first seen.
- Orders follow paper.py: insert-only, hash-chained, entry at the open after the order day,
  exit at the close, costs both ways, $1,000 per trade.
- **How it will be judged, fixed now:** after 10 closed trades, or 12 months, whichever comes
  first. It is kept only if its mean return after costs is positive. With about 10 Episodes a
  year, this is a slow test; it proves the machinery long before it proves the rule.
