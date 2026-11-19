# 8. v1 defers Portfolios; Recommendations are generic

Date: 2026-11-18
Status: Accepted. Amends ADR-0005 for v1.

## Context

ADR-0005 planned logged-in Users who connect Portfolios and get personalized Recommendations. The author currently holds a single index fund, so personalization has little practical value now, while Portfolios bring the most build work, privacy and security obligations, and the highest regulatory risk (personalized advice).

## Decision

- **v1 has no Portfolios.** No connection, storage or personalization.
- **Recommendations in v1 are generic**: impersonal views on Assets in the Asset universe, the same for every viewer, still built on and citing Analysis (ADR-0006).
- Portfolios and personalized Recommendations (manual entry and CSV import first, brokerage linking later) remain the intended later direction from ADR-0005.

## Consequences

- v1's regulatory exposure drops: generic, impersonal views are close to research or newsletter publishing.
- Recommendations are expressed against Assets, not holdings, so adding Portfolios later is a matter of mapping holdings onto Assets.
- **Visibility in v1 (settled):** the whole site sits behind a single shared **Passcode gate**. There are no per-user accounts. Inside, every Viewer sees Analysis and generic Recommendations, each labeled "not financial advice / educational" and linked to its Analysis. The site is not publicly open yet. The passcode is handed to reviewers when needed.
