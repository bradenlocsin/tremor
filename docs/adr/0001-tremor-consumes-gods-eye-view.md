# 1. TREMOR is a separate app that consumes gods-eye-view

Date: 2026-11-18
Status: Accepted

## Context

TREMOR is the geopolitical layer on top of live spatial data (aircraft, vessels, satellites, fires, quakes, infrastructure, and so on). That spatial data is already gathered and served by gods-eye-view, which the user has forked as `bradenlocsin/gods-eye-view` and which is also exposed as an MCP server.

## Decision

TREMOR is its own app in its own repo (`bradenlocsin/tremor`). It gets its sensor data from gods-eye-view through that project's MCP server or APIs. TREMOR owns the geopolitical model; gods-eye-view owns the sensors.

## Alternatives rejected

- **Build TREMOR inside the gods-eye-view fork**: rejected so we don't have to keep merging upstream changes into the fork, and so the geopolitics code doesn't mix with the sensor code.
- **Own all the data ingestion (ADS-B, AIS and so on)**: rejected because it rebuilds a solved problem before any geopolitical value exists.

## Consequences

- TREMOR depends on gods-eye-view being available and on the shape of its data. Changes upstream can break TREMOR.
- TREMOR needs its own map or display layer, or it uses gods-eye-view's `show_in_gods_eye_view` links.
