# 19. A hand-labeled eval set for LLM refinement

Date: 2026-11-18
Status: Accepted

## Decision

- About **100 Candidates**, labeled **blind** by the author through a labeling page in the Streamlit app. Fields: real event vs. noise, Event type, Region, duplicate or not. A "skip / unsure" option exists, and unsure items flag fuzzy taxonomy definitions.
- Labeling happens **once the first slice works** (taxonomy and Regions drafted, GDELT Candidates flowing) and **before** the refinement prompt is tuned.
- Every change to the refinement prompt or model is re-scored against the set: per-field accuracy and noise-rejection rate. Scores appear in the README.

## Alternatives rejected

- **LLM-as-judge**: AI grading AI is weak evidence.
- **Spot checks by eye**: produce no defensible number.
- **LLM pre-filled labels for the author to confirm**: anchoring would inflate the score.

## Consequences

- Each taxonomy entry needs a one-line definition plus an example, so labeling needs no domain expertise.
- A taxonomy change means adding or relabeling items.
