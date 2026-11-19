# 4. Portfolio-first, commercially clean, with a separable Recommendation layer

Date: 2026-11-18
Status: Accepted

## Context

TREMOR is a portfolio piece (ADR-0003), but a paid product for investors or analysts is a possible future. Two things would be expensive to undo later: data sources whose terms forbid commercial use, and output that counts as regulated investment advice. The user wants buy/sell-style advice for their own use.

## Decision

1. **Portfolio-first.** No niche or pricing model is chosen now.
2. **Every Source is tagged with its license** (commercial-OK or non-commercial). All of them may be used personally; a future paid version filters on the tag.
3. **Two output layers:**
   - **Analysis**: evidence of how Events have affected or may affect Assets. Always on.
   - **Recommendation**: actionable buy, sell or hedge views built on Analysis. It is a separate layer that can be **switched off**, and every Recommendation cites the Analysis it rests on.

## Alternatives rejected

- **Startup-first**: premature, since it pushes toward customer discovery before there is anything to show.
- **Portfolio only, ignoring commercial concerns**: would lock in licensing and advice problems that are expensive to undo.
- **Analysis only, with no advice**: rejected because the user wants recommendations for personal use. Making the layer switchable gives the same safety.

## Consequences

- Recommendation code and data must not be tangled into Analysis. Turning it off must leave Analysis fully working.
- Whether Recommendations appear in the public deployment is a separate decision.
