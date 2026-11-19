# 11. Comparables: Event type + Region, minimum N with an honest fallback

Date: 2026-11-18
Status: Accepted

## Context

Event studies (ADR-0010) average over "similar" past Events. How similarity is defined decides whether the Analysis is meaningful and explainable.

## Decision

- An Event's **Comparables** are past Events with the same **Event type** and **Region**.
- **Event type** comes from a TREMOR taxonomy of about 10–15 market-relevant types, assigned by the LLM during refinement (ADR-0007), starting from GDELT's codes.
- **Region** is a predefined zone (e.g. Red Sea / Bab-el-Mandeb, Strait of Hormuz, Taiwan Strait, Black Sea).
- **Minimum N = 8.** Below that, broaden to Event type only, and disclose the broadening on the chart.

## Alternatives rejected

- **Embedding similarity**: flexible, but hard to explain why two Events count as similar. A candidate later upgrade, to compare against this baseline.
- **Event type only**: ignores geography, which drives which Assets react.

## Consequences

- The taxonomy and Region list are curated artifacts that need versioning.
- Candidates outside the taxonomy are dropped before refinement, which also limits LLM cost.
