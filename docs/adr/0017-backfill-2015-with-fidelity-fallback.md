# 17. Backfill from 2015, with a fallback chain and a Fidelity flag

Date: 2026-11-18
Status: Accepted

## Context

Event studies need history. GDELT 2.0 carries article URLs from 2015, but many older URLs are dead, and LLM refinement (ADR-0007) reads the source article.

## Decision

Backfill Candidates from 2015 to today. Refine each using a fallback chain:
1. the live article
2. the Wayback Machine snapshot
3. GDELT's coded fields plus the headline only. The resulting Event is marked **lower Fidelity**.

If most of an event study's Comparables are lower Fidelity, Confidence is capped at Med.

## Alternatives rejected

- **Readable articles only**: biases history toward recent years and toward outlets that keep archives online.
- **No backfill**: no event studies for months.

## Consequences

- The backfill is a one-time LLM cost with its own budget, separate from the daily cap (ADR-0015). It can run one Region at a time.
- Every Event stores its Fidelity and which refinement path produced it, as part of its Provenance.

## Amendment (2026-11-19, during #9): cap refinement per day and Event type

The first 57 days of real backfill kept ~3,500 unique Red Sea URLs, which projects to ~240,000 over 2015–2026, or roughly $150 of Haiku refinement, far above the $20 backfill cap. Refinement therefore takes only the **3 most-covered URLs per day and Event type** (ranked by GDELT's article count), configurable with `--per-day`. A market-moving Event is almost always among the most-covered stories of its day, and Episodes (ADR-0020) collapse repeats anyway.

The dry run also showed that some dead links **redirect to the outlet's homepage**. Those are treated as dead, so the chain moves on to the Wayback Machine, and articles need at least 600 characters of text to count.
