"""Event-type taxonomy and Regions (ADR-0011). Loaded from config/taxonomy.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from tremor.config import REPO_ROOT

TAXONOMY_PATH = REPO_ROOT / "config" / "taxonomy.toml"


@dataclass(frozen=True)
class EventType:
    id: str
    name: str
    definition: str
    example: str
    cameo: tuple[str, ...]
    keywords: tuple[str, ...]
    first_slice: bool

    def matches_cameo(self, code: str) -> bool:
        return any(code.startswith(prefix) for prefix in self.cameo)

    def matches_keywords(self, text: str) -> bool:
        if not self.keywords:
            return True
        text = text.lower()
        return any(k in text for k in self.keywords)


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    lat: tuple[float, float]
    lon: tuple[float, float]
    first_slice: bool
    description: str = ""  # the Region in words, for prompts

    def contains(self, lat: float, lon: float) -> bool:
        return self.lat[0] <= lat <= self.lat[1] and self.lon[0] <= lon <= self.lon[1]


@dataclass(frozen=True)
class Taxonomy:
    version: int
    event_types: tuple[EventType, ...]
    regions: tuple[Region, ...]

    def event_type(self, type_id: str) -> EventType:
        for t in self.event_types:
            if t.id == type_id:
                return t
        raise KeyError(f"unknown Event type: {type_id}")

    def region(self, region_id: str) -> Region:
        for r in self.regions:
            if r.id == region_id:
                return r
        raise KeyError(f"unknown Region: {region_id}")

    def first_slice(self) -> "Taxonomy":
        """Only the first-slice Event types and Regions (ADR-0021)."""
        return Taxonomy(
            version=self.version,
            event_types=tuple(t for t in self.event_types if t.first_slice),
            regions=tuple(r for r in self.regions if r.first_slice),
        )

    def for_region(self, region_id: str) -> "Taxonomy":
        """The first-slice Event types with one Region (for a new Region's own pipeline)."""
        regions = tuple(r for r in self.regions if r.id == region_id)
        if not regions:
            raise ValueError(f"unknown Region {region_id!r}")
        return Taxonomy(version=self.version,
                        event_types=tuple(t for t in self.event_types if t.first_slice),
                        regions=regions)

    def region_for(self, lat: float, lon: float) -> Region | None:
        """First Region containing the point (Regions are checked in file order)."""
        return next((r for r in self.regions if r.contains(lat, lon)), None)

    def candidate_types(self, cameo_code: str, text: str) -> list[EventType]:
        """Event types a GDELT Candidate could belong to, from its CAMEO code and URL/title text."""
        return [
            t
            for t in self.event_types
            if (t.cameo and t.matches_cameo(cameo_code) and t.matches_keywords(text))
            or (not t.cameo and t.matches_keywords(text) and t.keywords)
        ]


def load_taxonomy(path: Path = TAXONOMY_PATH) -> Taxonomy:
    raw = tomllib.loads(Path(path).read_text())
    return Taxonomy(
        version=raw["version"],
        event_types=tuple(
            EventType(
                id=t["id"],
                name=t["name"],
                definition=t["definition"],
                example=t["example"],
                cameo=tuple(t["cameo"]),
                keywords=tuple(t["keywords"]),
                first_slice=t["first_slice"],
            )
            for t in raw["event_types"]
        ),
        regions=tuple(
            Region(
                id=r["id"],
                name=r["name"],
                lat=tuple(r["lat"]),
                lon=tuple(r["lon"]),
                first_slice=r["first_slice"],
                description=" ".join(r.get("description", "").split()),
            )
            for r in raw["regions"]
        ),
    )


@cache
def default_taxonomy() -> Taxonomy:
    return load_taxonomy()
