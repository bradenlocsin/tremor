# 28. Multiple-testing correction and placebo tests

Date: 2026-11-19
Status: Accepted (amends ADR-0010 and ADR-0012)

## Context

A Recommendation required a significant CAR (p < 0.05) for one Asset at +5 or +20 trading days. Each Analysis runs 10 such tests (5 Assets × 2 days), so even with no real effects, about 40% of Analyses (1 − 0.95¹⁰) would contain at least one "significant" result by chance, and each would become a Recommendation. TREMOR's own Comparable counts are small (often 8–15), and the evidence standard is the product's main selling point.

## Decision

1. **Benjamini–Hochberg correction.** Within each Analysis, the family is every Asset × decision day (+5, +20) with enough Comparables. A headline is significant only if its BH q-value is below α (0.05). Raw p-values are kept and shown next to q. Recommendations store `q_value`. Day +1 stays descriptive and is outside the family.
2. **Placebo test** (`tremor placebo`). For an Event type and Region, the identical event study is rerun on 1,000 random draws of pseudo-event dates, each draw the same size N as the real Comparables. Pseudo dates exclude any trading day within a window length plus the estimation gap of a real Event. The test reports two numbers:
   - **chance p<.05**: the share of random draws that look significant, which is the test's real false-alarm rate on this data.
   - **placebo p**: the share of random-date mean CARs at least as extreme as the real one (Monte Carlo randomization inference).

## Consequences

- Fewer Recommendations, and each is harder to dismiss as a lucky draw.
- First run, on the 6 hand-verified Red Sea shipping attacks: chance p<.05 rates of 4–6% (the cross-sectional t-test is well calibrated here) and placebo p-values of 0.16–0.95, confirming that the hand-verified sample alone shows nothing beyond chance.
- The placebo test takes about 15 seconds for 5 Assets × 3 days × 1,000 draws. It is a reporting tool, not part of the hourly job.
- Still open: robust tests for event-induced variance and overlapping windows (#52), and benchmark robustness for commodity Assets (#53).
