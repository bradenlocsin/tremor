# 7. Event pipeline: GDELT detects, LLM refines

Date: 2026-11-18
Status: Accepted

## Context

Event studies (ADR-0006) need a long history of Events. gods-eye-view sensor data cannot detect geopolitical Events or supply that history. GDELT is free, updates every 15 minutes, goes back decades, and carries a source article URL per record, but it is coded automatically and noisy.

## Decision

One pipeline:

1. **GDELT detects** Candidate Events, filtered to market-relevant event types and regions.
2. **The LLM refines** each Candidate by reading its source article. It produces a clean Event (what happened, Actors, location, severity) and maps the Event to Assets.
3. **Sensor data enriches** Events, for example vessels near a chokepoint. It does not detect them.

History for event studies comes from GDELT. LLM refinement runs on historical Candidates only for the subset being studied.

## Alternatives rejected

- **ACLED as the primary source**: narrower (conflict and protest only) and its license restricts commercial use. It may be added later as a second Source, tagged non-commercial.
- **A separate news API with LLM extraction for live Events, in parallel with GDELT**: slightly lower latency, but twice the plumbing and two definitions of Event.
- **GDELT without LLM refinement**: too noisy for trustworthy Analysis.

## Consequences

- One definition of Event, with a Candidate stage before it.
- LLM cost grows with the number of Candidates, so filtering before refinement matters.
- Refinement quality needs an evaluation set.
- Check GDELT's terms of use and record its License tag.
