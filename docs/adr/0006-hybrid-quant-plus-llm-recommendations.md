# 6. Hybrid: quant engine produces numbers, LLM produces reasoning

Date: 2026-11-18
Status: Accepted

## Context

Recommendations (ADR-0004, ADR-0005) must be trustworthy, explainable and testable against past data. TREMOR is also meant to show both finance and applied-AI skill.

## Decision

- **Quant engine (deterministic)** produces Analysis through **event studies**: for an Event, find similar past Events and measure what the linked Assets actually did in the days that followed.
- **LLM** (Claude) classifies incoming Events, maps Events to Assets, and writes Recommendations for a User's Portfolio. It may only reason from the quant Analysis and must cite it.

## Alternatives rejected

- **LLM end to end**: fast to build, but hard to trust, explain or back-test.
- **No AI**: loses the applied-AI part of the portfolio goal, and Event classification and Asset mapping would be weaker.

## Consequences

- TREMOR needs historical price data for Assets and a history of past Events to run event studies.
- LLM output must be checked for grounding: a Recommendation that cites no Analysis is invalid.
- Event classification quality decides which past Events count as "similar", so it needs evaluation.
