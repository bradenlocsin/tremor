"""LLM refinement: Candidates → Events (ADR-0007, ADR-0017, ADR-0022).

For each Candidate source URL (most-covered first, capped per day and Event type):
  1. get the article text through the fallback chain
       live article → Wayback Machine snapshot → GDELT fields + headline from the URL (lower Fidelity)
  2. ask the refinement model for a structured verdict (real Event or noise; Event type; Actors; ...)
  3. save real Events; mark the Candidates refined / rejected

Spend is recorded per call and checked against the daily or backfill budget before each call.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Literal, Protocol
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from tremor.config import Config
from tremor.events import Event, save_events
from tremor.gdelt import FRESH_SQL
from tremor.taxonomy import Taxonomy

USER_AGENT = "Mozilla/5.0 (compatible; tremor-research/0.1)"
MAX_ARTICLE_CHARS = 12_000
MIN_ARTICLE_CHARS = 600

# Prices per million tokens (input, output), from the Claude API reference cached 2026-11-03.
# Haiku 5.5's price applies to prompts up to 100K tokens, which refinement never exceeds.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "fake": (0.0, 0.0),
}

SPEND_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_spend (
    at          TEXT NOT NULL,
    day         TEXT NOT NULL,
    model       TEXT NOT NULL,
    purpose     TEXT NOT NULL,     -- refine | backfill | rationale
    input_tok   INTEGER NOT NULL,
    output_tok  INTEGER NOT NULL,
    usd         REAL NOT NULL
);
"""


# ---------------------------------------------------------------- structured output


class Refinement(BaseModel):
    """What the refinement model returns for one article."""

    is_real_event: bool = Field(
        description="True only if the article reports a specific thing that actually happened "
        "(not opinion, analysis, an anniversary, a threat-only story, or a rehash)."
    )
    noise_reason: str | None = Field(
        default=None, description="If not a real event: one short phrase why."
    )
    event_type: str = Field(description="One taxonomy Event type id, or 'none'.")
    title: str = Field(description="Neutral one-line headline of what happened.")
    occurred_on: str = Field(description="ISO date (YYYY-MM-DD) when it happened, per the article.")
    actors: list[str] = Field(description="States, groups, companies or leaders involved.")
    severity: int = Field(ge=1, le=5, description="1 minor … 5 major market-relevant escalation.")
    summary: str = Field(description="Two sentences, only facts stated in the article.")
    affected_assets: list[str] = Field(
        description="Tickers from the provided Asset list this event plausibly moves."
    )


@dataclass(frozen=True)
class Usage:
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def usd(self) -> float:
        p_in, p_out = PRICES.get(self.model, (0.0, 0.0))
        return (self.input_tokens * p_in + self.output_tokens * p_out) / 1_000_000


class Refiner(Protocol):
    model: str

    def refine(self, system: str, prompt: str) -> tuple[Refinement, Usage]: ...


class ClaudeRefiner:
    """Refinement through the Anthropic SDK's structured-output helper (messages.parse)."""

    def __init__(self, model: str):
        import anthropic

        self.model = model
        self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY or an `ant auth login` profile

    def refine(self, system: str, prompt: str) -> tuple[Refinement, Usage]:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=2000,
            output_config={"effort": "low"},
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            output_format=Refinement,
        )
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise RuntimeError(f"refinement returned no structured output ({response.stop_reason})")
        u = response.usage
        return response.parsed_output, Usage(self.model, u.input_tokens, u.output_tokens)


class FakeRefiner:
    """Deterministic stand-in for tests and dry runs: trusts the GDELT Candidate type."""

    model = "fake"

    def refine(self, system: str, prompt: str) -> tuple[Refinement, Usage]:
        meta = json.loads(prompt.split("CANDIDATE_JSON:", 1)[1].split("\n", 1)[0])
        types = meta["candidate_types"]
        noise = any(w in meta["source_url"].lower() for w in ("opinion", "analysis", "anniversary"))
        return (
            Refinement(
                is_real_event=not noise,
                noise_reason="opinion/analysis" if noise else None,
                event_type=types[0] if types and not noise else "none",
                title=meta["headline"] or "untitled",
                occurred_on=meta["event_date"],
                actors=[a for a in (meta["actor1"], meta["actor2"]) if a],
                severity=2,
                summary="(fake refinement)",
                affected_assets=[],
            ),
            Usage(self.model, 0, 0),
        )


# ---------------------------------------------------------------- article fetching


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "header", "aside"):
            self._skip += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header", "aside") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip and len(data.strip()) > 40:
            self.parts.append(data.strip())


def html_to_text(html: str) -> tuple[str, str]:
    p = _TextExtractor()
    p.feed(html)
    return p.title.strip(), "\n".join(p.parts)[:MAX_ARTICLE_CHARS]


def redirected_to_front_page(requested: str, final: str) -> bool:
    """Dead articles often redirect to the outlet's homepage or a section index."""
    req, fin = urlparse(requested), urlparse(final)
    return fin.path.strip("/").count("/") < 1 and len(fin.path.strip("/")) < 25 and (
        fin.path.strip("/") != req.path.strip("/")
    )


def _get(url: str, timeout: int = 20) -> str | None:
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout) as r:
            if r.status != 200 or redirected_to_front_page(url, r.geturl()):
                return None
            return r.read(2_000_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - any failure moves to the next step of the chain
        return None


def wayback_url(url: str, day: str) -> str | None:
    api = f"https://archive.org/wayback/available?url={quote(url, safe='')}&timestamp={day.replace('-', '')}"
    body = _get(api)
    if not body:
        return None
    try:
        snap = json.loads(body).get("archived_snapshots", {}).get("closest", {})
    except json.JSONDecodeError:
        return None
    return snap.get("url") if snap.get("available") else None


def headline_from_url(url: str) -> str:
    slug = max(urlparse(url).path.split("/"), key=len)
    slug = re.sub(r"\.(html?|php|aspx?)$", "", slug)
    words = [w for w in re.split(r"[-_]+", slug) if w and not w.isdigit()]
    return " ".join(words)[:200]


@dataclass(frozen=True)
class Article:
    path: str  # live | wayback | gdelt-only
    title: str
    text: str

    @property
    def fidelity(self) -> str:
        return "lower" if self.path == "gdelt-only" else "full"


def fetch_article(url: str, day: str, fetch=_get) -> Article:
    """The fallback chain (ADR-0017)."""
    html = fetch(url)
    if html:
        title, text = html_to_text(html)
        if len(text) >= MIN_ARTICLE_CHARS:
            return Article("live", title, text)
    snap = wayback_url(url, day) if fetch is _get else None
    if snap:
        html = fetch(snap)
        if html:
            title, text = html_to_text(html)
            if len(text) >= MIN_ARTICLE_CHARS:
                return Article("wayback", title, text)
    return Article("gdelt-only", headline_from_url(url), "")


# ---------------------------------------------------------------- prompts


def system_prompt(tax: Taxonomy, tickers: list[str]) -> str:
    types = "\n".join(f"- {t.id}: {t.definition} Example: {t.example}" for t in tax.event_types)
    return f"""You turn news articles into structured geopolitical Events for a market-analysis tool.

Decide whether the article reports a specific event that actually happened, and if so classify it.
Classify only what the article itself says. Do not use anything you know about later events or
outcomes, and do not infer facts the article doesn't state.

Event types (use exactly one id, or "none" when no type fits):
{types}

Not a real event: opinion or analysis pieces, explainers, anniversaries, threats with no action
(unless the type is military_threat), statements that something "could" or "may" happen, and
roundups that only rehash earlier events.

affected_assets: choose only from these tickers, and only when the link is direct: {", ".join(tickers)}.
Return an empty list when unsure."""


def user_prompt(cand: dict, article: Article) -> str:
    meta = {
        "source_url": cand["source_url"],
        "event_date": cand["event_date"],
        "candidate_types": json.loads(cand["candidate_types"]),
        "actor1": cand["actor1"],
        "actor2": cand["actor2"],
        "place": cand["place"],
        "headline": article.title,
    }
    body = article.text or "(article unavailable; judge from the headline and GDELT fields only)"
    return f"CANDIDATE_JSON:{json.dumps(meta)}\nARTICLE ({article.path}):\n{body}"


# ---------------------------------------------------------------- budget


class BudgetExceeded(Exception):
    pass


def spent(conn: sqlite3.Connection, purpose: str, day: str | None = None) -> float:
    conn.executescript(SPEND_SCHEMA)
    if day:
        row = conn.execute(
            "SELECT COALESCE(SUM(usd), 0) FROM llm_spend WHERE purpose = ? AND day = ?",
            (purpose, day),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COALESCE(SUM(usd), 0) FROM llm_spend WHERE purpose = ?", (purpose,)
        ).fetchone()
    return float(row[0])


def record_spend(conn: sqlite3.Connection, usage: Usage, purpose: str) -> None:
    now = datetime.now(UTC)
    conn.execute(
        "INSERT INTO llm_spend VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now.isoformat(timespec="seconds"), now.date().isoformat(), usage.model, purpose,
         usage.input_tokens, usage.output_tokens, usage.usd),
    )


# ---------------------------------------------------------------- the refinement run


def pick_candidates(
    conn: sqlite3.Connection, region: str, per_day_per_type: int, since: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """One row per unrefined source URL, keeping the most-covered URLs per day and type."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        WITH urls AS (
          SELECT source_url, MIN(event_date) AS event_date, candidate_types,
                 MAX(actor1) AS actor1, MAX(actor2) AS actor2, MAX(place) AS place,
                 AVG(lat) AS lat, AVG(lon) AS lon,
                 SUM(num_articles) AS coverage
          FROM candidates
          WHERE status = 'new' AND region = ? AND (? IS NULL OR event_date >= ?)
            AND {fresh}
          GROUP BY source_url
        ), ranked AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY event_date, candidate_types ORDER BY coverage DESC) AS rk
          FROM urls
        )
        SELECT * FROM ranked WHERE rk <= ? ORDER BY event_date DESC, coverage DESC
        """.format(fresh=FRESH_SQL),
        (region, since, since, per_day_per_type),
    ).fetchall()
    conn.row_factory = None
    out = [dict(r) for r in rows]
    return out[:limit] if limit else out


def event_id_for(url: str) -> str:
    return "gdelt-" + hashlib.sha1(url.encode()).hexdigest()[:16]


def refine_candidates(
    conn: sqlite3.Connection,
    cfg: Config,
    tax: Taxonomy,
    refiner: Refiner,
    region: str = "red_sea",
    purpose: str = "refine",
    per_day_per_type: int = 3,
    since: str | None = None,
    limit: int | None = None,
    fetch=_get,
    log=print,
) -> dict[str, int]:
    conn.executescript(SPEND_SCHEMA)
    cap = cfg.backfill_llm_usd if purpose == "backfill" else cfg.daily_llm_usd
    today = date.today().isoformat()
    tickers = [a.ticker for a in cfg.assets]
    system = system_prompt(tax, tickers)
    valid_types = {t.id for t in tax.event_types}
    stats = {"events": 0, "rejected": 0, "skipped_budget": 0, "errors": 0}

    for cand in pick_candidates(conn, region, per_day_per_type, since, limit):
        already = spent(conn, purpose, None if purpose == "backfill" else today)
        if already >= cap:
            stats["skipped_budget"] += 1
            continue
        article = fetch_article(cand["source_url"], cand["event_date"], fetch=fetch)
        try:
            result, usage = refiner.refine(system, user_prompt(cand, article))
        except Exception as e:  # noqa: BLE001
            log(f"  refine failed for {cand['source_url']}: {e}")
            stats["errors"] += 1
            continue
        record_spend(conn, usage, purpose)

        if result.is_real_event and result.event_type in valid_types:
            try:
                occurred = date.fromisoformat(result.occurred_on)
            except ValueError:
                occurred = date.fromisoformat(cand["event_date"])
            save_events(conn, [Event(
                id=event_id_for(cand["source_url"]),
                title=result.title,
                event_type=result.event_type,
                region=region,
                occurred_on=occurred,
                reported_at=cand["event_date"],
                actors=tuple(result.actors),
                summary=result.summary,
                source_url=cand["source_url"],
                source_name=urlparse(cand["source_url"]).netloc,
                license="commercial",  # derived facts + GDELT record; article text is not stored
                fidelity=article.fidelity,
                origin="gdelt",
                refinement_path=article.path,
                model=usage.model,
                taxonomy_version=tax.version,
                severity=result.severity,
                assets=tuple(t for t in result.affected_assets if t in tickers),
                lat=cand.get("lat"),
                lon=cand.get("lon"),
            )])
            status = "refined"
            stats["events"] += 1
        else:
            status = "rejected"
            stats["rejected"] += 1
        conn.execute(
            "UPDATE candidates SET status = ? WHERE source_url = ?", (status, cand["source_url"])
        )
        conn.commit()
    return stats
