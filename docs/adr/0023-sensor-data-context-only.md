# 23. Sensor data is context only in v1, plus a daily chokepoint recorder

Date: 2026-11-18
Status: Accepted

## Context

gods-eye-view Sensor data is live, with little or no history, so it cannot feed event studies for past Events (ADR-0010).

## Decision

- In v1, Sensor data is **context only**. It is shown on the 2D map and passed to the Sonnet rationale for new Events (e.g. "vessel transits through Bab-el-Mandeb are well below normal"). It is **never** used in the quant Analysis.
- Built **last**, after step 4 of the first slice (ADR-0021).
- A cheap **daily recorder** job saves chokepoint vessel counts from gods-eye-view, building TREMOR's own sensor history.

## Alternatives rejected

- **Drop sensor enrichment from v1**: loses the context and the history-building head start.

## Consequences

- After about a year of recordings, a later phase can test whether sensor-confirmed Events move markets more.

## Amendment (2026-11-19, during #16): IMF PortWatch, read directly, with history

- gods-eye-view's chokepoint layer reads **IMF PortWatch** daily transit estimates (from AIS). gods-eye-view's own `/api` is served by its local server, not a public host, so TREMOR queries the same keyless PortWatch ArcGIS tables directly. This is a small exception to ADR-0001: same upstream, without the gods-eye-view hop.
- PortWatch **has history back to 2019**, so the "context only, no history" premise above no longer holds for chokepoint transits. 8,628 daily rows were recorded for Bab el-Mandeb, Suez and the Cape of Good Hope. The data shows the Red Sea crisis clearly: Bab el-Mandeb went from 78 transits/day (+2% vs. the prior 90 days) on 2023-11-18 to 37/day (−44%) by 2024-01-25, while the Cape of Good Hope rose 30%.
- v1 still uses it as **context only** (dashboard + rationale). The phase-2 test of whether sensor-confirmed Events move markets more can start now rather than after a year of recording.
- License tag: **non-commercial** (IMF terms: reuse with attribution, not for resale). The attribution is shown wherever the data appears.
- Recorded snapshots are Claims and carry Provenance and a License tag like any other.
