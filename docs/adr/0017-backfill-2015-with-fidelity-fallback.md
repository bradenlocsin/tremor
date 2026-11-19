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
