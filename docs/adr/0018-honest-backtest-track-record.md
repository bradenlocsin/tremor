# 18. An honest back-test drives the Track record

Date: 2026-11-18
Status: Accepted

## Decision

- For every historical Event, generate the Recommendation TREMOR would have made using **only Comparables that happened before it**, with no look-ahead.
- Score each one against the Asset's realized CAR at its horizon: hit rate, average CAR when right vs. wrong, and results broken down by Confidence.
- Live Recommendations are scored automatically once their horizon passes.
- A **Track record** page shows all of this.

## Alternatives rejected

- **Score live Recommendations only**: nothing to show for months.
- **No scoring**: an unscored claim isn't credible to a finance reviewer.

## Consequences

- The back-test scores the deterministic Stance and Confidence (ADR-0012) **before** any LLM downgrade, because the LLM's past reasoning can't be replayed faithfully. The Track record page says so.
- The LLM refining historical articles may know what happened afterward from its training data. Refinement prompts must classify only what the article says, and this residual risk is disclosed.
- Results are reported honestly even when the edge is modest.
