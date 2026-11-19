# 15. Two clocks: hourly Events, daily prices, with an LLM budget cap

Date: 2026-11-18
Status: Accepted

## Decision

- **Hourly:** pull new GDELT Candidates, filter them to the Event type taxonomy and Regions, LLM-refine the survivors, and update the Event feed.
- **Daily, after the US market close:** fetch new prices, then recompute Analysis and Recommendations for recent Events.
- **A daily LLM budget cap:** once the cap is hit, the remaining Candidates are deferred to the next day.

## Alternatives rejected

- **Every 15 minutes (GDELT's native cadence)**: about 4× the runs and LLM cost, while event studies use daily closes anyway.
- **Once a day for everything**: the Event feed feels stale in a demo.

## Consequences

- A newly refined Event gets its Analysis and Recommendation within the hour, because the event study averages its Comparables, whose prices already exist. Only the new Event's own realized CAR fills in daily, and the chart can overlay it on the Comparables' average as it develops.
- LLM spend has to be tracked per day.
