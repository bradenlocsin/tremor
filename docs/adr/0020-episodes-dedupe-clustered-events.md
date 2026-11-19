# 20. Episodes: only an Episode's first Event is a Comparable

Date: 2026-11-18
Status: Accepted

## Context

Real crises come in bursts (e.g. dozens of Red Sea shipping attacks in 2023–24). Counting each Event as a Comparable overlaps their event windows, inflates N and makes noise look significant (ADR-0010).

## Decision

- Events with the same Event type and Region, each within **10 trading days** of the previous one, form an **Episode**.
- Only an Episode's **first Event** counts as a Comparable.
- Later Events still appear in the Event feed, grouped under their Episode. They show the Episode's Analysis instead of producing their own Recommendation.

## Alternatives rejected

- **Count every Event, with clustered standard errors**: more rigorous, but harder to build and explain.
- **Ignore the clustering**: overstated significance.

## Consequences

- N counts Episodes, not Events. Some Comparable sets shrink, so the N ≥ 8 fallback (ADR-0011) triggers more often.
- The back-test (ADR-0018) generates Recommendations only at Episode starts.
- This replaces the earlier, informal "Theater" idea.
