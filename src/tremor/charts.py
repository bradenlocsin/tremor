"""Static event-study charts (PNG) for the README and reports.

Small multiples: one panel per Asset, each a single series (average CAR) with its 95% band.
Colors follow the dataviz reference palette; the interactive version lives in the dashboard.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from tremor.event_study import StudyResult  # noqa: E402

THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", grid="#e4e3df",
                  series="#2a78d6", band="#b7d3f6"),
    "dark": dict(surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", grid="#383835",
                 series="#3987e5", band="#184f95"),
}


def _pct(x: float, _pos=None) -> str:
    return f"{x * 100:+.0f}%" if abs(x) >= 0.01 or x == 0 else f"{x * 100:+.1f}%"


def plot_study(
    results: list[StudyResult], title: str, asset_names: dict[str, str], theme: str = "light"
):
    t = THEMES[theme]
    n_panels = len(results)
    fig, axes = plt.subplots(
        1, n_panels, figsize=(3.4 * n_panels, 4.0), sharey=False, facecolor=t["surface"]
    )
    axes = [axes] if n_panels == 1 else list(axes)
    for ax, r in zip(axes, results):
        ax.set_facecolor(t["surface"])
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(t["grid"])
        ax.tick_params(colors=t["ink2"], labelsize=8, length=0)
        ax.grid(axis="y", color=t["grid"], linewidth=0.8)
        ax.axhline(0, color=t["ink2"], linewidth=0.8)
        ax.axvline(0, color=t["ink2"], linewidth=0.8, linestyle=(0, (3, 3)))
        ax.yaxis.set_major_formatter(FuncFormatter(_pct))

        if r.n == 0:
            ax.text(0.5, 0.5, "no usable Comparables", transform=ax.transAxes,
                    ha="center", color=t["ink2"], fontsize=9)
        else:
            days = r.mean_car.index
            if r.n > 1:
                ax.fill_between(days, r.band_low, r.band_high, color=t["band"], alpha=0.55,
                                linewidth=0)
            ax.plot(days, r.mean_car, color=t["series"], linewidth=2, solid_capstyle="round")
            end = r.mean_car.iloc[-1]
            ax.annotate(_pct(end), (days[-1], end), xytext=(4, 0), textcoords="offset points",
                        va="center", fontsize=8, color=t["ink"])

        h20 = r.headlines.get(20)
        if h20 is None or r.n < 2:
            stat = f"N={r.n}"
        else:
            sig = "significant" if h20.significant else "not significant"
            stat = f"N={r.n}  ·  +20d p={h20.p_value:.2f} ({sig})"
        flags = []
        if r.insufficient:
            flags.append("below minimum N=8")
        if r.broadened:
            flags.append("broadened: Event type only")
        ax.text(0, 1.20, f"{r.asset}  ·  {asset_names.get(r.asset, '')}", fontsize=9.5,
                transform=ax.transAxes, color=t["ink"], va="bottom", fontweight="bold")
        ax.text(0, 1.03, stat + "\n" + (", ".join(flags) if flags else " "),
                transform=ax.transAxes, fontsize=7.5, color=t["ink2"], va="bottom",
                linespacing=1.4)
        ax.set_xlim(r.mean_car.index[0] - 0.5, r.mean_car.index[-1] + 4)
        ax.set_xlabel("trading days from Event", fontsize=8, color=t["ink2"])

    axes[0].set_ylabel("cumulative abnormal return", fontsize=8, color=t["ink2"])
    fig.suptitle(title + "  (each panel has its own scale)", x=0.01, ha="left", fontsize=12, color=t["ink"], fontweight="bold")
    fig.text(0.01, 0.005,
             "Average CAR vs. a market model on SPY, with 95% band. "
             "Prices: Yahoo Finance via yfinance (non-commercial). Not financial advice.",
             fontsize=7, color=t["ink2"])
    fig.tight_layout(rect=(0, 0.03, 1, 0.92))
    return fig


def save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


CHOKEPOINT_COLORS = {
    "light": {"Bab el-Mandeb Strait": "#2a78d6", "Suez Canal": "#eb6834",
              "Cape of Good Hope": "#1baf7a"},
    "dark": {"Bab el-Mandeb Strait": "#3987e5", "Suez Canal": "#d95926",
             "Cape of Good Hope": "#199e70"},
}


def plot_chokepoints(wide, start, end, marks: list[tuple[str, str]], theme: str = "light"):
    """7-day mean daily transits per chokepoint, lines labeled at their ends; dated event marks."""
    import pandas as pd

    t = THEMES[theme]
    w = wide.rolling(7, min_periods=4).mean()
    w = w[(w.index >= pd.Timestamp(start)) & (w.index <= pd.Timestamp(end))]
    fig, ax = plt.subplots(figsize=(11, 4.2), facecolor=t["surface"])
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["grid"])
    ax.tick_params(colors=t["ink2"], labelsize=8, length=0)
    ax.grid(axis="y", color=t["grid"], linewidth=0.8)
    for port in w.columns:
        s = w[port].dropna()
        color = CHOKEPOINT_COLORS[theme].get(port, t["ink2"])
        ax.plot(s.index, s.values, color=color, linewidth=2, label=port)
        ax.annotate(port, (s.index[-1], s.iloc[-1]), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=8.5, color=t["ink"])
    ymax = float(w.max().max()) * 1.25
    for i, (day, label) in enumerate(marks):  # staggered so nearby dates don't collide
        ax.axvline(pd.Timestamp(day), color=t["ink2"], linewidth=0.8, linestyle=(0, (3, 3)))
        ax.text(pd.Timestamp(day), ymax * (0.99 - 0.065 * i), " " + label, fontsize=7.5,
                color=t["ink2"], va="top")
    ax.set_ylim(0, ymax)
    ax.set_xlim(w.index.min(), w.index.max() + pd.Timedelta(days=70))
    ax.set_ylabel("ships per day (7-day mean)", fontsize=8, color=t["ink2"])
    ax.legend(loc="lower left", fontsize=8, frameon=False, labelcolor=t["ink"])
    fig.suptitle("Red Sea shipping before and after the 2023–24 attacks", x=0.01, ha="left",
                 fontsize=12, color=t["ink"], fontweight="bold")
    fig.text(0.01, 0.005, "Chokepoint transits: IMF PortWatch (International Monetary Fund and "
             "University of Oxford), estimated from ship AIS signals. Reuse with attribution, "
             "not for resale.", fontsize=7, color=t["ink2"])
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    return fig
