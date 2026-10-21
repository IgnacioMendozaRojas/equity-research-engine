"""Report figures in the shared style (figstyle): titles state the finding, light and dark versions."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from matplotlib.ticker import MaxNLocator

from .figstyle import charts

SOURCE = (
    "Source: company filings (SEC, CMF) and reports; model and assumptions in this repository. "
    "github.com/IgnacioMendozaRojas/equity-research-engine"
)


def lithium_prices(history: dict[int, float], decks: dict[str, dict[int, float]], out: Path) -> str:
    name = "lithium-price"
    yrs = sorted(history)
    peak_year = max(history, key=history.get)
    longrun = [d[max(d)] / 1000 for d in decks.values()]
    for c in charts(
        f"Realised lithium peaked at US${history[peak_year] / 1000:,.0f}k/t in {peak_year}; "
        f"the decks settle at US${min(longrun):,.0f}-{max(longrun):,.0f}k/t",
        "SQM average realised lithium price (lithium revenue / volume) and the model's price decks, "
        "US$ thousand per tonne, nominal",
        SOURCE,
    ):
        c.line(yrs, [history[y] / 1000 for y in yrs], 0, "SQM realised", marker="o", markersize=4)
        for i, (label, deck) in enumerate(decks.items(), start=1):
            dy = sorted(deck)
            c.line(dy, [deck[y] / 1000 for y in dy], i, label, linestyle=(0, (4, 3)))
        c.note((peak_year, history[peak_year] / 1000), "2022 spike: most of it went to the state", (25, -10))
        c.ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        c.ax.set_ylim(bottom=0)
        c.yaxis("US$ thousand per tonne")
        c.legend("upper left")
        c.save(out, name)
    return name


def value_by_segment(values: dict[str, float], labels: dict[str, str], out: Path, name: str, title=None) -> str:
    named = {labels.get(k, k): v / 1000 for k, v in values.items()}
    positive = {k: v for k, v in named.items() if v > 0}
    top = max(positive, key=positive.get)
    share = positive[top] / sum(positive.values())
    for c in charts(
        title or f"{top} is {share:.0%} of the enterprise value",
        "Present value of each business line's free cash flow, US$ billion",
        SOURCE,
        size=(9, 0.42 * len(named) + 2.4),
    ):
        c.hbars(list(named), list(named.values()), fmt="{:,.1f}", highlight={top})
        c.fig.subplots_adjust(left=0.4, right=0.92, top=0.72, bottom=0.22)
        c.save(out, name)
    return name


def distribution(values: np.ndarray, price: float, target: float, out: Path, name: str) -> str:
    v = np.asarray(values)
    hi = np.percentile(v, 99)
    p_above = np.mean(v > price)
    for c in charts(
        f"Only {p_above:.0%} of {len(v):,} simulated price paths value the shares above their price",
        "Monte Carlo distribution of DCF value per share, US$ (mean-reverting commodity prices)",
        SOURCE,
    ):
        c.ax.hist(v[v <= hi], bins=60, color=c.color(0), alpha=0.85)
        for x, label, i in [(price, "share price", 1), (target, "model value", None)]:
            c.ax.axvline(x, color=c.t["accent"] if i is None else c.color(i), linewidth=2)
            left = x < price  # the lower of the two lines is labelled on its left
            c.ax.text(
                x,
                0.97,
                f" {label} {x:,.1f} ",
                transform=c.ax.get_xaxis_transform(),
                color=c.t["text"],
                fontsize=8.5,
                va="top",
                ha="right" if left else "left",
            )
        c.ax.set_yticks([])
        c.ax.grid(False)
        c.xlabel("DCF value per share, US$")
        c.save(out, name)
    return name


def waterfall(
    steps: list[tuple[str, float]], out: Path, name: str, title=None, reference: tuple[str, float] | None = None
) -> str:
    first, last = steps[0][1], steps[-1][1]
    for c in charts(
        title or f"Hindsight lifts the 2020 value only from US${first:,.1f} to US${last:,.1f} per share",
        "October 2020 DCF value per share, replacing assumptions with what actually happened, US$",
        SOURCE,
    ):
        xs = np.arange(len(steps))
        prev = None
        for x, (_label, val) in zip(xs, steps, strict=True):
            if prev is None:
                c.ax.bar(x, val, color=c.t["grid"], width=0.55)
            else:
                d = val - prev
                c.ax.bar(x, d, bottom=prev, color=c.color(2) if d >= 0 else c.color(1), width=0.55)
            top = val if prev is None else max(val, prev)
            c.ax.annotate(
                f"{val:,.1f}",
                (x, top),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                fontsize=8.5,
                color=c.t["text"],
            )
            prev = val
        if reference:
            c.ax.axhline(reference[1], color=c.t["muted"], linewidth=1, linestyle=(0, (3, 3)))
            c.ax.text(
                len(steps) - 0.6,
                reference[1],
                f"{reference[0]} {reference[1]:,.1f}",
                color=c.t["text"],
                fontsize=8.5,
                va="bottom",
                ha="right",
            )
        c.ax.set_xticks(xs, [s[0] for s in steps], color=c.t["text"], fontsize=8.5)
        c.ax.set_ylim(0, max(v for _, v in steps) * 1.15)
        c.yaxis("US$ per share")
        c.fig.subplots_adjust(bottom=0.27)
        c.save(out, name)
    return name


def forecast_vs_actual(years, fcst, actual, out: Path, name: str, title=None, unit: str = "") -> str:
    f, a = np.asarray(fcst, float), np.asarray(actual, float)
    ratio = np.nanmax(a / f)
    for c in charts(
        title or f"Realised prices ran up to {ratio:.1f}x the October 2020 deck",
        f"October 2020 forecast vs reported, {unit}",
        SOURCE,
    ):
        c.line(
            list(years), f, 1, "Forecast, Oct 2020", end_label=False, linestyle=(0, (4, 3)), marker="o", markersize=4
        )
        c.line(list(years), a, 0, "Reported", end_label=False, marker="o", markersize=4)
        c.ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        c.ax.set_ylim(bottom=0)
        c.yaxis(unit)
        c.legend("upper left")
        c.save(out, name)
    return name
