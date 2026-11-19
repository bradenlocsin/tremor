# 29. Gemini on Antigravity CLI is a second backfill engine and audits Codex

Date: 2026-11-19
Status: Accepted (extends ADR-0027)

## Context

ADR-0027 left two gaps. The history backfill runs on Codex alone, so it moves at the pace of Codex's 5-hour usage windows (about 1,700 articles per window, about 15,000 left). And Codex labeled the Eval set as well as refining the history, so nothing independent checked Codex's own decisions.

The author has a Google AI student plan. Gemini CLI no longer serves personal accounts (June 2026), but its replacement, Antigravity CLI (`agy`), does. Its headless print mode (`agy -p`) supports a strict JSON schema. It offers Gemini 3.8 Flash (low, medium and high effort), Claude Sonnet 4.6 and Opus 4.6, and GPT-OSS.

## Decision

1. **`--engine agy`** runs the same batched refinement as Codex (`AgyRefiner` reuses `CodexRefiner`'s batching and exact-once id validation) on **Gemini 3.8 Flash, medium effort**. Events record `model = 'agy:gemini-3.8-flash-medium'`, and spend is $0.
2. **Two engines, one backfill.** Codex refines newest-first and Gemini refines oldest-first (`--oldest-first`), so they meet in the middle. `scripts/codex_supervisor.py --engine agy` keeps the Gemini run going across limits.
3. **`tremor audit`** re-refines a random sample of Codex's decisions with Gemini, blind to Codex's answer, half kept and half rejected. It reports keep/reject agreement and Cohen's kappa. **A third model family (Claude Opus 4.6, via agy) judges each disagreement**, seeing both answers and the article.

Antigravity print mode is told not to use tools. Without that, Gemini tries to read files, the call is denied, and it returns an empty answer, which the client treats as an error. A quota failure stops the run cleanly, like Codex's usage limit.

## Evidence

Eval test set, scored against the Codex panel labels (95 confident items):

| Engine | Kept-Event precision | Recall | Time per 10 items |
|---|---|---|---|
| Claude Haiku (API) | 94% | 61% | – |
| Gemini Flash, low effort | 85% | 82% | ~0.5 min |
| **Gemini Flash, medium effort** | **92%** | **79%** | ~2 min |
| Gemini Flash, high effort | – | – | ~4+ min per call; too slow |

Audit of 100 Codex history decisions with Gemini (medium): **86% agreement, kappa 0.72**, and the same Event type in 98% of the articles both kept. In 14 disagreements, the Opus judge:

- **Articles only Codex kept (10):** 6 sided with Codex, 1 with Gemini (a GDELT mismatch whose fetched text never mentions the Region), and 3 unsure (thin mentions inside news roundups).
- **Articles only Gemini kept (4):** 2 sided with Gemini (Events Codex missed), and 2 unsure.

Most of the disagreement comes from **news roundups**. Codex extracts the in-Region story buried in a multi-story article, while Gemini judges by the lead story. That makes Codex's keep precision on this sample about 92–98%.

## Consequences

- The backfill moves at roughly twice the speed, and the history now mixes two refiners. Every Event records its model, so the event study can be rerun on Codex-only Events as a robustness check.
- Gemini's recall is a little lower, mainly on roundups, so the older half of the history may hold slightly fewer Events than Codex would have found.
- The audit is agreement, not accuracy: two models can share a mistake. Its value is as a tripwire, plus a stored list of disputes (`audit_items`) with the judge's rulings for the case study.
