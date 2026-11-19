# 10. Event studies use market-model abnormal returns with significance

Date: 2026-11-18
Status: Accepted

## Context

Analysis is produced by event studies (ADR-0006). Raw returns mix in market-wide moves, and averages without statistics invite Recommendations built on noise.

## Decision

Follow the standard event-study method (MacKinlay, 1997):
- **Expected return**: a market model (Asset regressed on SPY) estimated over about 120 trading days before each Event.
- **Abnormal return (AR)**: the actual return minus the expected return.
- **Cumulative abnormal return (CAR)**: AR summed over the event window, day −1 through +20.
- Across similar past Events: the average CAR path with a confidence band and N.
- Headline numbers: CAR at +1, +5 and +20, each with a significance flag.

## Alternatives rejected

- **Raw returns**: confound Event effects with market-wide moves.
- **Abnormal returns without statistics**: no protection against acting on noise.

## Consequences

- Needs daily price history for SPY and every Asset in the Asset universe, covering the estimation window before the earliest studied Event.
- Recommendations should rely on significant results. Non-significant results are shown, but labeled as such.
- Overlapping Events (several in the same window) need handling so they aren't double-counted.
