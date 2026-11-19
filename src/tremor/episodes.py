"""Episodes (ADR-0020): bursts of same-type, same-Region Events.

Events with the same Event type and Region, each within `gap` trading days of the previous one,
form one Episode. Only an Episode's first Event counts as a Comparable: markets react to the
surprise, not the 27th repeat, and overlapping event windows would inflate N.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from tremor.events import Event


@dataclass(frozen=True)
class Episode:
    id: str
    event_type: str
    region: str
    start: date
    end: date
    events: tuple[Event, ...]

    @property
    def first(self) -> Event:
        return self.events[0]

    @property
    def size(self) -> int:
        return len(self.events)


def _trading_index(calendar: pd.DatetimeIndex, d: date) -> int:
    return int(calendar.searchsorted(pd.Timestamp(d)))


def build_episodes(events: list[Event], calendar: pd.DatetimeIndex, gap: int) -> list[Episode]:
    """Group Events into Episodes, measuring gaps in trading days on `calendar`."""
    groups: dict[tuple[str, str], list[Event]] = {}
    for e in events:
        groups.setdefault((e.event_type, e.region), []).append(e)

    episodes: list[Episode] = []
    for (etype, region), evs in groups.items():
        evs.sort(key=lambda e: (e.occurred_on, e.id))
        current: list[Event] = []
        last_idx = None
        for e in evs:
            idx = _trading_index(calendar, e.occurred_on)
            if current and last_idx is not None and idx - last_idx > gap:
                episodes.append(_make(etype, region, current))
                current = []
            current.append(e)
            last_idx = idx
        if current:
            episodes.append(_make(etype, region, current))
    episodes.sort(key=lambda ep: (ep.start, ep.event_type))
    return episodes


def _make(etype: str, region: str, evs: list[Event]) -> Episode:
    start, end = evs[0].occurred_on, evs[-1].occurred_on
    return Episode(
        id=f"ep-{region}-{etype}-{start.isoformat()}",
        event_type=etype,
        region=region,
        start=start,
        end=end,
        events=tuple(evs),
    )


def episode_starts(episodes: list[Episode]) -> list[Event]:
    """The Events that may serve as Comparables."""
    return [ep.first for ep in episodes]


def episode_of(event_id: str, episodes: list[Episode]) -> Episode | None:
    for ep in episodes:
        if any(e.id == event_id for e in ep.events):
            return ep
    return None
