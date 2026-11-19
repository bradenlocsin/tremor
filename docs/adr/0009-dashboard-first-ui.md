# 9. Dashboard-first UI; the 3D globe is a link-out

Date: 2026-11-18
Status: Accepted

## Context

TREMOR comes from gods-eye-view, a 3D globe, but it is now finance-first (ADR-0003) and consumes gods-eye-view instead of extending it (ADR-0001).

## Decision

v1's main screen is a dashboard:
- an **Event feed**
- for the selected Event, the **Analysis**: an event-study chart of how similar past Events moved each linked Asset
- the **Recommendation** card
- a small **2D map** pinning the Event and its Sensor data enrichment, with a "view in 3D" link to gods-eye-view

## Alternatives rejected

- **Globe-first**: the flashier hook, but it rebuilds gods-eye-view and pushes the finance to the side.
- **Report-first (a daily brief)**: a possible later feature, not the main screen.

## Consequences

- The event-study chart is the centerpiece and deserves the most design care.
- TREMOR needs only a lightweight 2D map, not a 3D engine.
