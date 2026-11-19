# 12. Recommendations: the numbers decide, the LLM explains

Date: 2026-11-18
Status: Accepted

## Context

ADR-0006 split the work: the quant engine produces numbers and the LLM produces reasoning. Recommendations need to be auditable and must not rest on noise (ADR-0010).

## Decision

- A Recommendation exists **only if** an Asset's CAR is significant at +5 or +20 trading days. Otherwise: "No Recommendation: historical effect not distinguishable from noise."
- **Stance** (Overweight / Underweight) and **horizon** (5 or 20 trading days) come deterministically from the sign and window of the significant CAR.
- **Confidence** (Low / Med / High) is computed from N, the effect size, and whether the Comparables were broadened.
- **The LLM writes the rationale**: how this Event resembles its Comparables and what is different this time. It may **downgrade** Confidence but can never upgrade it or flip the Stance.

## Alternatives rejected

- **LLM decides stance and confidence**: less auditable, and open to unsupported claims.
- **Numbers only, no rationale**: loses the explanation and the applied-AI showcase.

## Consequences

- Every Recommendation can be reproduced from its Analysis, apart from LLM downgrades, which must be stored with their stated reason.
- The wording uses institutional research language (Overweight / Underweight), not buy/sell, which fits the "not financial advice" framing.
