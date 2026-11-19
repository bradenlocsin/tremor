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
- Recorded snapshots are Claims and carry Provenance and a License tag like any other.
