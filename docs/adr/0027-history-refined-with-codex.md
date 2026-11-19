# 27. The history backfill is refined with Codex; live runs stay on Claude Haiku

Date: 2026-11-19
Status: Accepted (amends ADR-0017)

## Context

Refining the full GDELT history (about 21,500 articles) with Claude Haiku would cost about $8 of a prepaid $20 API balance. The author has unused Codex CLI subscription capacity and asked to use it wherever possible.

## Decision

`tremor refine --backfill --engine codex` refines the history with Codex CLI (`gpt-6.2-sol`):

- 10 articles per ephemeral, read-only session, with 6 sessions in parallel.
- The same system prompt, taxonomy and Region check as Claude refinement, and the same `Refinement` fields under a strict JSON schema.
- Article text is marked as untrusted data in the prompt.
- Every Event records `model = 'codex:gpt-6.2-sol'`, and spend is recorded as $0.

Daily live refinement in the deployed product stays on **Claude Haiku**, which is a pay-per-use API meant for production. The Anthropic balance is kept for live runs, Sonnet rationales and Eval comparisons.

## Consequences

- **Eval caveat.** The Codex panel that labels the Eval set (ADR-0025) is the same model family as the Codex refiner, so a Codex refiner score against panel labels is inflated by shared judgment. **Haiku's score is the independent measure** and is the one reported as the pipeline's accuracy; any Codex score is reported as agreement only.
- History Events come from a stronger model than live Events. The Eval set measures both, so the gap is visible.
- A Codex session can return fewer results than the items it was sent. Each missing item becomes an error, and the Candidate stays `new`, so rerunning the backfill retries it.
