# 5. Public Analysis; personalized Recommendations behind login

Date: 2026-11-18
Status: Accepted. Amended by ADR-0008: Portfolios are deferred past v1.

## Context

ADR-0004 split output into Analysis (always on) and a switchable Recommendation layer, and left open whether Recommendations appear publicly.

## Decision

- **Public (logged-out):** Analysis only.
- **Logged-in Users** connect their Portfolio and get **personalized Recommendations** for it.

## Alternatives rejected

- **Impersonal Recommendations shown publicly**: the user prefers that public viewers see Analysis only.
- **Recommendations only for the author**: the user wants other logged-in Users to get them too.

## Consequences

- TREMOR needs auth, per-User data and Portfolio storage, so it is a multi-user app.
- **Regulatory risk:** personalized, portfolio-aware recommendations for third parties is the investment-adviser category. Keep access invite-only and free until a legal opinion is obtained. Open signups or payment require that review first. The Recommendation switch (ADR-0004) is the fallback.
- Holding Portfolio data creates privacy and security obligations. How Portfolios get connected is still open.
