# 14. yfinance for v1 prices, behind a swappable price-source interface

Date: 2026-11-18
Status: Accepted

## Context

Event studies (ADR-0010) need daily price history for SPY and the Asset universe, going back far enough to cover estimation windows before historical Events.

## Decision

Use **yfinance** (unofficial Yahoo Finance data) for v1, tagged **non-commercial** (ADR-0004). All price access goes through a small price-source interface.

## Alternatives rejected

- **A licensed provider's free tier (e.g. Tiingo)**: cleaner terms, but still usually personal-use only, rate-limited and keyed.
- **Alpha Vantage free tier**: 25 requests a day is too few to back-fill the Asset universe.

## Consequences

- A commercial version must swap to a licensed provider (e.g. Tiingo or Polygon, paid). The interface keeps that cheap.
- yfinance is unofficial and occasionally breaks, so cache prices locally and don't refetch history.
