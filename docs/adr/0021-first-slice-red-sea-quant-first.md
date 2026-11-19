# 21. First slice: Red Sea, built quant-first

Date: 2026-11-18
Status: Accepted

## Decision

**Scope of the first slice:**
- Region: Red Sea / Bab-el-Mandeb
- Event types: shipping attack, military strike, chokepoint disruption
- Assets: BNO (oil), GLD (gold), ITA (defense), BDRY (shipping, history from 2018 only), UUP (dollar)

**Build order:**
1. Quant core: prices plus the event-study engine, run on about a dozen hand-entered Red Sea Events. No GDELT or LLM yet.
2. GDELT ingestion and LLM refinement, then the Eval set (ADR-0019).
3. Episodes, Recommendations, back-test, Track record.
4. Streamlit dashboard, Passcode gate, deployment.
5. Widen to more Regions and the full Asset universe.

**Flagship case study:** "The 2023–24 Red Sea crisis: what TREMOR would have said, and how it did."

## Alternatives rejected

- **Pipeline-first**: no financially meaningful output until late.
- **Taiwan Strait or Strait of Hormuz as the flagship**: viable later. The Red Sea is recent, well covered (so mostly full Fidelity), clearly market-moving, and fits gods-eye-view's vessel tracking.

## Consequences

- An Asset's ETF start date limits its Comparables (e.g. BDRY from 2018). Event studies must drop Comparables whose estimation window starts before an Asset existed, and show the effect on N.
- If work stalls after step 1, there is still a working finance artifact.
