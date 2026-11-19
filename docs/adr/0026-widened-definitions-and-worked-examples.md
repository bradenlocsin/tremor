# 26. Widened Red Sea Event definitions, and worked examples for refinement

Date: 2026-11-19
Status: Accepted (amends ADR-0011 and ADR-0019)

## Context

The first Eval run (taxonomy v2, Codex panel labels per ADR-0025) found that Haiku and Sonnet each kept about the same share of wrong Events (56% and 54% precision). Almost every disagreement sat on a boundary in TREMOR's own definitions, not on a model mistake:

- **Attacks on warships.** The models counted a Houthi drone attack on HMS Richmond as a shipping attack. The panel didn't, because the definition said *commercial* vessel.
- **Announced blockades.** The models counted the Houthis' declared ban on Israel-linked ships as a chokepoint disruption. The panel didn't, because nothing had been physically stopped yet.
- **Small boats.** Examples were a sailing trimaran boarded, or coalition forces destroying Houthi boats.

In late 2023, freight and war-risk insurance rates moved on announcements and on attacks on warships, before most physical disruption. For a market-reaction tool, the narrower definitions excluded the very news that moved prices.

Sonnet found more real Events (82% recall vs. 59%), but at roughly 20 times Haiku's price, a full-history Sonnet refinement (~$160) is far beyond the budget.

## Decision

1. **Taxonomy v3.** The changes:
   - **shipping_attack** covers any vessel in the Region's waters, commercial or naval, including missiles or drones aimed at it that are shot down.
   - Strikes on an armed group's own boats, launch sites or weapons at sea are a **military_strike**.
   - **chokepoint_disruption** includes an announced blockade, closure or transit ban by a party able to enforce it.
2. **Worked examples, not fine-tuning.** Haiku stays the refinement model. Its system prompt gets about 16 worked examples chosen from panel-agreed labels. The prompt is cached, so the extra input costs about 0.1× the normal price, and cached reads don't count toward rate limits.
   - A separate **teach** split of the Eval set (40 new Candidates) supplies the examples.
   - The scored **test** split (the original 100) never supplies examples, so the score isn't graded on answers the model was shown.
   - Each example is the panel's own paraphrase plus its verdict and reasoning. No article text is stored.
   - `tremor eval examples` writes `config/refine_examples.json`. That file is part of the prompt, so changing it changes the prompt hash recorded on every Eval run.
3. **Cost tracking counts cached tokens**: writes at 1.25× the input price and reads at 0.1× (0.05× on Sonnet 5.5). This keeps the budget caps honest.

## Consequences

- Events refined under v2 are discarded and the history is refined again under v3, at a cost of about $1.
- The Eval set is relabeled by the panel under v3 before scoring.
- Fine-tuning stays out of scope: it would need far more labels than the project has, and it isn't self-serve for current Claude models.
