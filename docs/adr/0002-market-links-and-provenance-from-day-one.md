# 2. Market links and provenance from day one

Date: 2026-11-18
Status: Accepted

## Context

TREMOR's first user is its author, a solo analyst. A possible later use is informing financial decisions, and a public version may come later still.

## Decision

1. **Market links are in scope from the start.** TREMOR links geopolitical happenings to tradable Assets so it can answer "what does this mean for X?"
2. **Every Claim carries provenance**: its Source, plus a timestamp of when the claim was observed or reported.

## Alternatives rejected

- **Provenance now, market links later**: rejected because the user wants the financial angle designed in, not added on later.
- **Ignore the financial use until later**: rejected for the same reason.
- **Claims and links without provenance**: rejected. Acting financially requires knowing what was known, when, and from where, and trust in a market link is only as good as its basis.

## Consequences

- The data model needs a Source and a timestamp on every stored Claim, including market links.
- Timestamps must tell the time something *happened* apart from the time TREMOR *learned* it.
