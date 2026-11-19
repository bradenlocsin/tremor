# 24. Renamed from GAIA to TREMOR

Date: 2026-11-18
Status: Accepted

## Context

The project began as "GAIA" (Geopolitical Awareness & Intelligence Atlas), named when it was a geopolitical layer. After the finance-first reframing (ADR-0003), that name no longer described the product. GAIA is also the Nasdaq ticker of Gaia, Inc., which would be confusing for a finance product.

## Decision

The product is **TREMOR: Tracking Risk Events & Market Outcome Reactions**. The metaphor: a geopolitical shock sends tremors through markets, and TREMOR measures them. The GitHub repo is `bradenlocsin/tremor`. All docs were updated in place.

## Alternatives rejected

- **Keep GAIA with a new expansion** ("Geopolitical Asset Impact Analysis" or "Geopolitical Alpha & Impact Analytics"): keeps continuity, but the ticker collision remains.
- **SEISMIC, CATALYST, Aftershock, Flashpoint**: forced acronyms, or more geopolitical than financial.

## Consequences

- Trademarks and existing products named "TREMOR" were not checked. Check before any commercial use (ADR-0004).
- The local working folder is still `~/globe`. Renaming it is optional.
