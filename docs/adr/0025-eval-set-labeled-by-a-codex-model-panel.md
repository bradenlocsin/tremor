# 25. The Eval set is labeled by a Codex model panel

Date: 2026-11-19
Status: Accepted (amends ADR-0019)

## Context

ADR-0019 planned for the author to hand-label the ~100 Eval set items. The author chose not to: they don't yet have the domain background to judge borderline articles better than a strong model, and preferred to spend their Codex subscription over the small Anthropic API balance.

## Decision

The Eval set is labeled by a **three-role panel of independent Codex CLI sessions** (`tremor eval panel`, default model `gpt-6.2-sol`):

1. **Labeler**: labels each article blind. It never sees TREMOR's own refinement output.
2. **Skeptic**: sees the article plus the labeler's label, is told to refute it, and gives its own label.
3. **Judge**: only for items where the two disagree; reads both arguments and rules. Rulings it isn't confident in are stored as *unsure*, which scoring excludes.

Articles are fetched once with the same live → Wayback → headline chain as refinement, and passed in the prompt. Codex runs read-only, with no network, in an empty directory, and is told the article text is untrusted data. A real event outside the taxonomy is labeled as noise, matching how refinement treats it. Every label stores `labeled_by = 'panel:<model>'` and the panel's reasoning in `note`.

## Consequences

- **These labels are model labels, not human ground truth.** Eval results are reported as *agreement with an independent model panel* and say so wherever they appear (dashboard, case study).
- Using a different model family (OpenAI) from the models being scored (Claude Haiku and Sonnet) reduces, but does not remove, shared blind spots.
- It costs no Anthropic API credit, and it is reproducible: `tremor eval panel` relabels the set.
- The labeling page still works. A hand label replaces a panel label for the same item, so the author can audit and override the panel later, starting with disputed items.
