"""TREMOR dashboard (ADR-0009). Run: uv run streamlit run src/tremor/dashboard/app.py

The whole site sits behind one shared passcode (ADR-0008), read from the TREMOR_PASSCODE
environment variable or Streamlit secrets. Without a configured passcode the app stays locked.
"""

from __future__ import annotations

import hmac
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tremor.analysis import analyze_event, analyze_group, episodes_for
from tremor.backtest import summarize, Call
from tremor.config import load_config
from tremor.event_study import daily_returns, event_car
from tremor.events import load_events
from tremor.prices import load_prices
from tremor.recommend import DISCLAIMER, decide
from tremor.storage import connect
from tremor.taxonomy import default_taxonomy

SERIES_1, SERIES_2, BAND = "#2a78d6", "#eb6834", "rgba(42,120,214,0.18)"
# Categorical slots 1–3 (validated light + dark with the dataviz validator; aqua needs labels)
CHOKEPOINT_COLORS = {"Bab el-Mandeb Strait": "#2a78d6", "Suez Canal": "#eb6834",
                     "Cape of Good Hope": "#1baf7a"}
GODS_EYE_VIEW = "https://godseyeview.ai/online/"

st.set_page_config(page_title="TREMOR", page_icon="📉", layout="wide")


# ---------------------------------------------------------------- passcode gate


def configured_passcode() -> str | None:
    if os.environ.get("TREMOR_PASSCODE"):
        return os.environ["TREMOR_PASSCODE"]
    try:
        return st.secrets.get("passcode")
    except Exception:  # noqa: BLE001 - no secrets file
        return None


def gate() -> None:
    expected = configured_passcode()
    if not expected:
        st.error("TREMOR is locked: no passcode is configured (set TREMOR_PASSCODE).")
        st.stop()
    if st.session_state.get("unlocked"):
        return
    st.title("TREMOR")
    st.caption("Tracking Risk Events & Market Outcome Reactions")
    code = st.text_input("Passcode", type="password")
    if code and hmac.compare_digest(code, expected):
        st.session_state["unlocked"] = True
        st.rerun()
    elif code:
        st.error("Wrong passcode.")
    st.stop()


# ---------------------------------------------------------------- data


@st.cache_data(ttl=300)
def load():
    cfg = load_config()
    conn = connect(cfg.storage_path)
    events = load_events(conn)
    prices = load_prices(conn, cfg.tickers)
    try:
        bt = pd.read_sql_query("SELECT * FROM backtest", conn)
    except Exception:  # noqa: BLE001
        bt = pd.DataFrame()
    try:
        live = pd.read_sql_query(
            "SELECT r.*, s.realized_car, s.hit FROM recommendations r"
            " LEFT JOIN rec_scores s ON s.rec_id = r.id WHERE r.stance IS NOT NULL", conn)
    except Exception:  # noqa: BLE001
        live = pd.DataFrame()
    try:
        saved = pd.read_sql_query("SELECT * FROM recommendations", conn)
    except Exception:  # noqa: BLE001
        saved = pd.DataFrame()
    from tremor.sensors import transits

    chokepoints = transits(conn, "red_sea")
    return cfg, events, prices, bt, live, saved, chokepoints


def chokepoint_chart(wide: pd.DataFrame, when) -> go.Figure:
    """Daily transits, 7-day mean, ±120 days around the Event; lines labeled at their ends."""
    t = pd.Timestamp(when)
    w = wide.rolling(7, min_periods=4).mean()
    w = w[(w.index >= t - pd.Timedelta(days=120)) & (w.index <= t + pd.Timedelta(days=120))]
    fig = go.Figure()
    for port in w.columns:
        s = w[port].dropna()
        if s.empty:
            continue
        color = CHOKEPOINT_COLORS.get(port, "#52514e")
        fig.add_trace(go.Scatter(x=s.index, y=s, mode="lines", name=port,
                                 line=dict(color=color, width=2),
                                 hovertemplate="%{x|%Y-%m-%d}: %{y:.0f} ships/day<extra>" + port
                                 + "</extra>"))
        fig.add_annotation(x=s.index[-1], y=s.iloc[-1], text=port, showarrow=False,
                           xanchor="left", xshift=6, font=dict(size=11))
    if not w.empty and w.index.min() <= t <= w.index.max():
        fig.add_vline(x=t, line_width=1, line_dash="dot", line_color="gray")
    fig.update_layout(height=300, margin=dict(l=10, r=150, t=30, b=10), hovermode="x unified",
                      yaxis=dict(title="ships per day (7-day mean)", rangemode="tozero"),
                      legend=dict(orientation="h", y=1.15, x=0))
    return fig


def pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def car_chart(result, own_car: pd.Series | None, asset: str) -> go.Figure:
    days = list(result.mean_car.index)
    fig = go.Figure()
    if result.n > 1:
        fig.add_trace(go.Scatter(x=days + days[::-1],
                                 y=list(result.band_high) + list(result.band_low[::-1]),
                                 fill="toself", fillcolor=BAND, line=dict(width=0),
                                 hoverinfo="skip", name="95% band", showlegend=False))
    fig.add_trace(go.Scatter(x=days, y=result.mean_car, mode="lines", line=dict(color=SERIES_1, width=2),
                             name=f"Comparables average (N={result.n})",
                             hovertemplate="day %{x}: %{y:.2%}<extra>average</extra>"))
    if own_car is not None and len(own_car):
        fig.add_trace(go.Scatter(x=list(own_car.index), y=own_car, mode="lines+markers",
                                 line=dict(color=SERIES_2, width=2), marker=dict(size=8),
                                 name="This Event (realized)",
                                 hovertemplate="day %{x}: %{y:.2%}<extra>this Event</extra>"))
    fig.add_hline(y=0, line_width=1, line_color="gray")
    fig.add_vline(x=0, line_width=1, line_dash="dot", line_color="gray")
    fig.update_layout(
        height=360, margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified",
        yaxis=dict(tickformat=".0%", title="cumulative abnormal return"),
        xaxis=dict(title="trading days from Event"),
        legend=dict(orientation="h", y=1.12, x=0),
        title=dict(text=asset, x=0, font=dict(size=14)),
    )
    return fig


# ---------------------------------------------------------------- overview

# Diverging pair for "moved up" vs "moved down" relative to the market, neutral gray midpoint.
UP, DOWN, NEUTRAL, MUTED = "#2a78d6", "#eb6834", "#ecebe8", "#8a8985"
HORIZONS = (5, 20)


def short_name(asset) -> str:
    """'commodity: oil' -> 'Oil', 'sector: shipping (freight proxy)' -> 'Shipping'."""
    label = asset.category.split(": ", 1)[-1].split(" (")[0]
    return label[:1].upper() + label[1:]


@st.cache_data(ttl=3600, show_spinner="Running the event studies…")
def findings():
    """Event study for every first-slice Event type in the Red Sea, per Asset."""
    cfg, events, prices, *_ = load()
    tax = default_taxonomy().first_slice()
    return {t.id: analyze_group(t.id, "red_sea", events, prices, cfg) for t in tax.event_types}


def findings_chart(res: dict, cfg, day: int) -> go.Figure:
    tax = default_taxonomy()
    types = list(res)
    assets = cfg.assets
    z, zsig, text, hover = [], [], [], []
    for t in types:
        zr, sr, tr, hr = [], [], [], []
        for a in assets:
            r = res[t][a.ticker]
            h = r.headlines.get(day)
            car = h.mean_car if h else float("nan")
            sig = bool(h and h.significant)
            zr.append(car)
            sr.append(car if sig else None)
            tr.append("–" if car != car else f"<b>{car * 100:+.1f}%</b>" + (" ✓" if sig else "")
                      + f"<br><span style='font-size:11px'>{r.n} cases</span>")
            verdict = ("reliable (passes the multiple-testing check)" if sig else
                       "too few past cases" if r.insufficient else "not distinguishable from noise")
            hr.append(f"{tax.event_type(t).name} → {short_name(a)} ({a.ticker})<br>"
                      f"average move vs market after {day} trading days: "
                      f"{'–' if car != car else pct(car)}<br>{r.n} past cases · {verdict}")
        z.append(zr); zsig.append(sr); text.append(tr); hover.append(hr)
    rows = [tax.event_type(t).name for t in types]
    cols = [f"<b>{short_name(a)}</b><br>{a.ticker}" for a in assets]
    lim = max([abs(v) for row in z for v in row if v == v] + [0.01])
    fig = go.Figure()
    fig.add_trace(go.Heatmap(z=[[0 if v == v else None for v in row] for row in z], x=cols,
                             y=rows, colorscale=[[0, NEUTRAL], [1, NEUTRAL]], showscale=False,
                             text=text, texttemplate="%{text}",
                             textfont=dict(color=MUTED, size=15),
                             hovertext=hover, hoverinfo="text", xgap=2, ygap=2))
    fig.add_trace(go.Heatmap(z=zsig, x=cols, y=rows, zmin=-lim, zmax=lim, zmid=0,
                             colorscale=[[0, DOWN], [0.5, NEUTRAL], [1, UP]], showscale=False,
                             text=text, texttemplate="%{text}",
                             textfont=dict(color="#1c1b19", size=15),
                             hovertext=hover, hoverinfo="text", xgap=2, ygap=2))
    fig.update_layout(height=100 + 80 * len(rows), margin=dict(l=10, r=10, t=10, b=10),
                      yaxis=dict(autorange="reversed", tickfont=dict(size=14)),
                      xaxis=dict(side="top", tickfont=dict(size=13)))
    return fig


def overview_page(cfg, events, prices, bt):
    tax = default_taxonomy()
    st.title("TREMOR")
    st.markdown("##### When something happens in the Red Sea, how do markets react, "
                "and can that reaction be predicted?")
    st.write(
        "TREMOR reads the news, keeps only real geopolitical events, and measures how oil, gold, "
        "defense stocks, shipping and the dollar moved after every similar event in the past. It "
        "only makes a call when the history is strong enough to pass statistical checks, and it "
        "scores every call honestly."
    )

    first = default_taxonomy().first_slice()
    ids = {t.id for t in first.event_types}
    red = [e for e in events if e.region == "red_sea" and e.event_type in ids]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Events tracked", f"{len(red):,}")
    if red:
        k2.metric("History from", str(min(e.occurred_on for e in red).year))
        k3.metric("Latest Event", max(e.occurred_on for e in red).strftime("%b %-d, %Y"))
    if not bt.empty:
        calls = [Call(**{k: r[k] for k in Call.__dataclass_fields__}) for _, r in bt.iterrows()]
        k4.metric("Back-tested calls right", f"{summarize(calls).hit_rate.iloc[0]:.0%}",
                  help=f"Out of {len(calls)} calls made without hindsight.")
    else:
        k4.metric("Back-tested calls", "pending", help="Runs once the history is fully loaded.")

    st.markdown("#### What history says")
    day = st.radio("Horizon", HORIZONS, horizontal=True, key="ov_day",
                   format_func=lambda d: f"{d} trading days later")
    res = findings()
    st.plotly_chart(findings_chart(res, cfg, day), width="stretch",
                    config={"displayModeBar": False})
    st.caption(
        "Each cell is the average move of the Asset relative to the S&P 500 after past Events of "
        "that type (cases = how many past Events it averages). Colored cells with ✓ are reliable: they pass a "
        "significance test corrected for testing many combinations at once. Gray cells are not "
        "reliable yet, because there are too few cases or the effect is too small to tell apart "
        "from normal market noise."
    )
    reliable = [(t, a, res[t][a.ticker]) for t in res for a in cfg.assets
                if (h := res[t][a.ticker].headlines.get(day)) and h.significant]
    if reliable:
        for t, a, r in reliable:
            h = r.headlines[day]
            word = "rose" if h.mean_car > 0 else "fell"
            st.markdown(f"- After **{tax.event_type(t).name.lower()}s**, **{short_name(a)}** "
                        f"({a.ticker}) {word} **{abs(h.mean_car) * 100:.1f}%** more than the "
                        f"market over {day} trading days on average ({r.n} past cases).")
    else:
        st.info("No reaction is statistically reliable at this horizon yet. That is an honest "
                "result, not a bug: the full history is still loading, and many effects that "
                "look large are within normal market noise.")

    st.markdown("#### Latest Events")
    eps = sorted(episodes_for(red, prices, cfg), key=lambda ep: ep.end, reverse=True)[:6]
    for ep in eps:
        last = max(ep.events, key=lambda e: e.occurred_on)
        more = (f" · part of a run of {ep.size} related Events since {ep.start:%b %-d, %Y}"
                if ep.size > 1 else "")
        st.markdown(f"**{last.occurred_on:%b %-d, %Y}** · "
                    f"{tax.event_type(ep.event_type).name}{more}  \n{last.title}")
    st.caption("Open **Events** in the sidebar for the full analysis of any Event.")

    with st.expander("How it works"):
        st.markdown(
            "1. **Detect.** Every hour TREMOR pulls Red Sea news from GDELT, a global news "
            "database. AI models read each article and keep it only if it reports a real event "
            "of a tracked type (shipping attack, military strike, chokepoint disruption). They "
            "are checked against a labeled test set and against each other.\n"
            "2. **Measure.** For each Event it runs an *event study*: how each Asset moved "
            "relative to the S&P 500 in the days after every comparable past Event.\n"
            "3. **Call.** A Recommendation is made only when enough past cases agree and the "
            "result survives a multiple-testing correction and a placebo check against random "
            "dates. Every call is back-tested without hindsight and scored in the **Track "
            "record**."
        )


# ---------------------------------------------------------------- pages


def events_page(cfg, events, prices, saved, chokepoints):
    tax = default_taxonomy()
    if not events:
        st.info("No Events yet. Run `uv run tremor seed` or the GDELT pipeline.")
        return
    episodes = episodes_for(events, prices, cfg)
    episodes.sort(key=lambda ep: ep.end, reverse=True)
    by_id = {e.id: e for e in events}

    feed, main = st.columns([1, 2.3], gap="large")
    with feed:
        st.subheader("Event feed")
        labels = []
        for ep in episodes:
            kind = tax.event_type(ep.event_type).name
            size = f"  ·  Episode of {ep.size}" if ep.size > 1 else ""
            labels.append(f"{ep.first.occurred_on}  ·  {kind}{size}\n{ep.first.title[:80]}")
        choice = st.radio("Episodes, newest first", range(len(episodes)),
                          format_func=lambda i: labels[i], label_visibility="collapsed",
                          key="episode")
    ep = episodes[choice]
    target = ep.first

    with main:
        st.subheader(target.title)
        meta = [str(target.occurred_on), tax.event_type(target.event_type).name,
                tax.region(target.region).name, f"Fidelity: {target.fidelity}"]
        st.caption("  ·  ".join(meta))
        if target.actors:
            st.caption("Actors: " + ", ".join(target.actors))
        if target.source_url:
            st.caption(f"Source: [{target.source_name or 'link'}]({target.source_url})")
        if ep.size > 1:
            with st.expander(f"{ep.size} Events in this Episode ({ep.start} → {ep.end})"):
                for e in ep.events:
                    st.write(f"{e.occurred_on} — {e.title}")

        analysis = analyze_event(target, events, prices, cfg, episodes)
        returns = daily_returns(prices, cfg.benchmark)
        st.markdown("#### Analysis")
        asset = st.radio("Asset", [a.ticker for a in cfg.assets], horizontal=True, key="asset",
                         format_func=lambda t: f"{t} · {next(a.category for a in cfg.assets if a.ticker == t)}")
        result = analysis.results[asset]
        own = event_car(returns, target, asset, cfg.benchmark, cfg.event_study)
        st.plotly_chart(car_chart(result, None if isinstance(own, str) else own.car, asset),
                        width="stretch")
        flags = []
        if result.insufficient:
            flags.append(f"N={result.n} is below the minimum of {cfg.event_study.min_comparables}: "
                         "shown for context, no Recommendation can rely on it.")
        if result.broadened:
            flags.append("Comparables broadened to this Event type in every Region.")
        for f in flags:
            st.warning(f)

        rows = []
        for a in cfg.assets:
            r = analysis.results[a.ticker]
            row = {"Asset": f"{short_name(a)} ({a.ticker})", "Past cases": r.n}
            for d, h in r.headlines.items():
                row[f"Move vs market, +{d}d"] = pct(h.mean_car)
                row[f"p-value +{d}d"] = f"{h.p_value:.2f}" if h.p_value == h.p_value else "–"
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("Move vs market: the Asset's average return beyond what the S&P 500 explains "
                   "(cumulative abnormal return). A p-value below 0.05 means the move would be "
                   "unlikely by chance alone; Recommendations also require the stricter "
                   "multiple-testing check.")

        st.markdown("#### Recommendation")
        if not cfg.recommendations_enabled:
            st.info("The Recommendation layer is switched off (ADR-0004). Analysis above is unaffected.")
            return
        st.caption(DISCLAIMER)
        fidelity = {k: e.fidelity for k, e in by_id.items()}
        cols = st.columns(len(cfg.assets))
        for col, a in zip(cols, cfg.assets):
            rec = decide(target, a.ticker, analysis.results[a.ticker], fidelity)
            stored = saved[saved.id == f"{target.id}:{a.ticker}"] if len(saved) else saved
            with col, st.container(border=True):
                st.markdown(f"**{a.ticker}**")
                if rec.exists:
                    st.markdown(f"**{rec.stance}** · {rec.horizon_days} trading days")
                    conf = stored.confidence.iloc[0] if len(stored) and stored.confidence.iloc[0] else rec.confidence
                    st.caption(f"Confidence {conf} · CAR {pct(rec.mean_car)} · N={rec.n}")
                    if len(stored) and stored.rationale.iloc[0]:
                        st.write(stored.rationale.iloc[0])
                        if stored.downgrade_reason.iloc[0]:
                            st.caption(f"Downgraded: {stored.downgrade_reason.iloc[0]}")
                else:
                    st.caption(f"No Recommendation: {rec.no_rec_reason}")

        if target.region == "red_sea" and not chokepoints.empty:
            from tremor.sensors import ATTRIBUTION, context

            st.markdown("#### Shipping through the chokepoints")
            st.caption("Sensor context only: never used in the Analysis above (ADR-0023).")
            st.plotly_chart(chokepoint_chart(chokepoints, target.occurred_on), width="stretch")
            for c in context(chokepoints, target.occurred_on):
                st.caption(c.sentence())
            st.caption(ATTRIBUTION + " (reuse with attribution, not for resale).")

        if target.lat is not None and target.lon is not None:
            st.markdown("#### Where")
            st.map(pd.DataFrame({"lat": [target.lat], "lon": [target.lon]}), zoom=4, height=260)
            st.link_button("View live sensors in 3D (gods-eye-view)", GODS_EYE_VIEW)
            st.caption(f"Location: {target.lat:.2f}, {target.lon:.2f}")


def track_record_page(bt: pd.DataFrame, live: pd.DataFrame):
    st.subheader("Track record")
    st.caption(
        "Back-test: for every historical Episode start, the Recommendation TREMOR would have made "
        "using only Comparables and prices available the day before (no look-ahead), scored "
        "against what the Asset actually did. It scores the deterministic Stance and Confidence, "
        "before any LLM downgrade, because the LLM's past reasoning can't be replayed. "
        "The refinement model may also know later history from its training data; prompts tell "
        "it to classify only what each article says, but some risk remains. " + DISCLAIMER
    )
    if bt.empty:
        st.info("No back-tested calls yet: they need at least 8 earlier Episodes of a type. "
                "Run the GDELT pipeline and `uv run tremor backtest`.")
    else:
        calls = [Call(**{k: r[k] for k in Call.__dataclass_fields__}) for _, r in bt.iterrows()]
        s = summarize(calls)
        for c in ("hit_rate",):
            s[c] = s[c].map(lambda x: f"{x:.0%}")
        for c in ("avg_signed_car", "avg_car_when_right", "avg_car_when_wrong"):
            s[c] = s[c].map(lambda x: pct(x) if x == x else "–")
        st.dataframe(s, hide_index=True, width="stretch")
        with st.expander(f"All {len(bt)} back-tested calls"):
            st.dataframe(bt, hide_index=True, width="stretch")
    st.markdown("#### Live Recommendations")
    if live.empty:
        st.caption("No live Recommendations yet.")
    else:
        st.dataframe(live[["event_id", "asset", "stance", "horizon_days", "confidence",
                           "mean_car", "realized_car", "hit"]], hide_index=True,
                     width="stretch")


@st.cache_data(ttl=3600, show_spinner="Fetching the article…")
def article_for(url: str, day: str):
    from tremor.refine import fetch_article

    a = fetch_article(url, day)
    return a.path, a.title, a.text


def label_page(cfg):
    from tremor import evalset
    from tremor.refine import headline_from_url

    tax = default_taxonomy().first_slice()
    conn = connect(cfg.storage_path)
    done, total = evalset.progress(conn)
    st.subheader("Label the Eval set")
    st.caption(
        "Label each Candidate blind: decide from the article alone, not from what any model "
        "thinks. Unsure is a fine answer; it marks a fuzzy taxonomy edge. ~1–2 minutes each."
    )
    if total == 0:
        st.info("No Eval items yet. Run `uv run tremor eval sample` after the GDELT backfill.")
        return
    st.progress(done / total, text=f"{done} / {total} labeled")
    item = evalset.next_unlabeled(conn)
    if item is None:
        st.success("All items are labeled. Score a model with `uv run tremor eval score`.")
        return

    path, title, text = article_for(item["source_url"], item["event_date"])
    with st.container(border=True):
        st.markdown(f"**{title or headline_from_url(item['source_url'])}**")
        st.caption(f"GDELT date {item['event_date']} · location {item.get('place') or '?'} · "
                   f"[open the article]({item['source_url']}) · text from: {path}")
        st.write(text[:1500] + ("…" if len(text) > 1500 else "") if text
                 else "_Article text unavailable: judge from the headline and link._")

    with st.expander("Cheat sheet: Event type definitions"):
        for t in tax.event_types:
            st.markdown(f"**{t.name}** (`{t.id}`): {t.definition}  \n_e.g. {t.example}_")
        st.markdown("**Not a real event:** opinion or analysis, explainers, anniversaries, "
                    "'could/may' stories, roundups that only rehash earlier events.")

    with st.form(f"label-{item['source_url']}"):
        real = st.radio("1. Is this a real event?", ["Yes", "No (noise)", "Unsure"],
                        horizontal=True, index=None)
        etype = st.selectbox("2. Event type", ["none"] + [t.id for t in tax.event_types],
                             format_func=lambda i: "none / not applicable" if i == "none"
                             else tax.event_type(i).name)
        region = st.selectbox("3. Region", [r.id for r in tax.regions] + ["none"],
                              format_func=lambda i: "outside every Region" if i == "none"
                              else tax.region(i).name)
        dup = st.checkbox("4. Duplicate of an earlier story about the same event")
        note = st.text_input("Note (optional)")
        if st.form_submit_button("Save and next", type="primary"):
            if real is None:
                st.error("Answer question 1 first.")
            else:
                is_real = {"Yes": True, "No (noise)": False, "Unsure": None}[real]
                evalset.save_label(conn, item["source_url"], is_real, etype, region, dup, note)
                st.rerun()


def main():
    gate()
    cfg, events, prices, bt, live, saved, chokepoints = load()
    st.sidebar.title("TREMOR")
    st.sidebar.caption("Tracking Risk Events & Market Outcome Reactions")
    page = st.sidebar.radio("Page", ["Overview", "Events", "Track record"], key="page")
    st.sidebar.divider()
    st.sidebar.caption(DISCLAIMER)
    st.sidebar.caption("Prices: Yahoo Finance via yfinance (non-commercial). Events: GDELT, "
                       "refined by AI models (Claude, Codex, Gemini).")
    if page == "Overview":
        overview_page(cfg, events, prices, bt)
    elif page == "Events":
        events_page(cfg, events, prices, saved, chokepoints)
    elif page == "Track record":
        track_record_page(bt, live)


main()
