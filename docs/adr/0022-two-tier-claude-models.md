# 22. Two Claude model tiers, with the Eval set as referee

Date: 2026-11-18
Status: Accepted

## Decision

- **Claude Haiku 5.5** (`claude-haiku-5-5`) for LLM refinement: high volume (hourly Candidates plus the backfill), structured extraction.
- **Claude Sonnet 5.5** (`claude-sonnet-5-5`) for Recommendation rationales and Confidence downgrades: low volume, where reasoning and wording quality matter.
- The Eval set (ADR-0019) decides whether Haiku is good enough for refinement. If not, refinement moves to Sonnet and the README reports the comparison.

## Alternatives rejected

- **Sonnet for everything**: much higher backfill cost.
- **Haiku for everything**: the rationales are what reviewers read.

## Consequences

- Model IDs live in config, not code, so a tier can change without code edits.
- The daily budget cap (ADR-0015) tracks spend per model.
