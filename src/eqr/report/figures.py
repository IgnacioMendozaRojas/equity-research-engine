"""Report figures, each saved in a light and a dark version for GitHub's <picture> tag."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

THEMES = {
    "light": {
        "bg": "#fcfcfb",
        "fg": "#2b2b29",
        "muted": "#6e6e6a",
        "grid": "#e6e6e3",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
    },
    "dark": {
        "bg": "#1a1a19",
        "fg": "#e8e8e5",
        "muted": "#a3a39e",
        "grid": "#33332f",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500"],
    },
}


def _style(ax, t):
    ax.set_facecolor(t["bg"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(t["grid"])
    ax.tick_params(colors=t["muted"], labelsize=9)
    ax.yaxis.grid(True, color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def _save(fig, out: Path, name: str, theme: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{name}-{theme}.png", dpi=160, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def _title(ax, t, title, subtitle=None):
    ax.set_title(title, loc="left", color=t["fg"], fontsize=12, fontweight="bold", pad=22 if subtitle else 8)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, color=t["muted"], fontsize=9)


def lithium_prices(history: dict[int, float], decks: dict[str, dict[int, float]], out: Path) -> str:
    name = "lithium-price"
    for theme, t in THEMES.items():
        fig, ax = plt.subplots(figsize=(8, 4), facecolor=t["bg"])
        _style(ax, t)
        yrs = sorted(history)
        ax.plot(yrs, [history[y] / 1000 for y in yrs], color=t["fg"], lw=2.2, marker="o", ms=4)
        ax.annotate(
            "SQM realised",
            (yrs[-1], history[yrs[-1]] / 1000),
            xytext=(6, -2),
            textcoords="offset points",
            color=t["fg"],
            fontsize=9,
        )
        for i, (label, deck) in enumerate(decks.items()):
            dy = sorted(deck)
            c = t["series"][i]
            ax.plot(dy, [deck[y] / 1000 for y in dy], color=c, lw=2, ls="--")
            ax.annotate(
                label, (dy[-1], deck[dy[-1]] / 1000), xytext=(6, 0), textcoords="offset points", color=c, fontsize=9
            )
        ax.set_ylabel("US$ thousand per tonne", color=t["muted"], fontsize=9)
        _title(
            ax,
            t,
            "Lithium: realised price vs the price decks",
            "SQM average realised price (lithium revenue / volume) and model decks, nominal",
        )
        ax.set_xlim(min(yrs) - 0.5, max(max(d) for d in decks.values()) + 3)
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        _save(fig, out, name, theme)
    return name


def value_by_segment(values: dict[str, float], labels: dict[str, str], out: Path, name: str, title: str) -> str:
    items = sorted(values.items(), key=lambda kv: kv[1])
    for theme, t in THEMES.items():
        fig, ax = plt.subplots(figsize=(8, 0.45 * len(items) + 1.2), facecolor=t["bg"])
        _style(ax, t)
        ax.yaxis.grid(False)
        ax.xaxis.grid(True, color=t["grid"], linewidth=0.8)
        ys = np.arange(len(items))
        ax.barh(ys, [v / 1000 for _, v in items], color=t["series"][0], height=0.6)
        ax.set_yticks(ys, [labels.get(k, k) for k, _ in items], color=t["fg"])
        for y, (_, v) in zip(ys, items, strict=True):
            ax.text(v / 1000, y, f"  {v / 1000:,.1f}", va="center", color=t["fg"], fontsize=9)
        ax.set_xlabel("US$ billion, present value", color=t["muted"], fontsize=9)
        _title(ax, t, title)
        _save(fig, out, name, theme)
    return name


def distribution(values: np.ndarray, price: float, target: float, out: Path, name: str) -> str:
    v = np.asarray(values)
    hi = np.percentile(v, 99)
    for theme, t in THEMES.items():
        fig, ax = plt.subplots(figsize=(8, 4), facecolor=t["bg"])
        _style(ax, t)
        ax.hist(v[v <= hi], bins=60, color=t["series"][0], alpha=0.85)
        for x, label, c in [(price, "share price", t["series"][1]), (target, "target", t["fg"])]:
            ax.axvline(x, color=c, lw=2)
            ax.text(x, ax.get_ylim()[1] * 0.95, f" {label} {x:,.1f}", color=c, fontsize=9, va="top")
        ax.set_xlabel("DCF value per share, US$", color=t["muted"], fontsize=9)
        ax.set_yticks([])
        _title(
            ax,
            t,
            "Monte Carlo: value per share",
            f"{len(v):,} commodity price paths; {np.mean(v > price):.0%} above the share price",
        )
        _save(fig, out, name, theme)
    return name


def waterfall(
    steps: list[tuple[str, float]], out: Path, name: str, title: str, reference: tuple[str, float] | None = None
) -> str:
    for theme, t in THEMES.items():
        fig, ax = plt.subplots(figsize=(8, 4.2), facecolor=t["bg"])
        _style(ax, t)
        xs = np.arange(len(steps))
        prev = None
        for x, (_label, val) in zip(xs, steps, strict=True):
            if prev is None:
                ax.bar(x, val, color=t["muted"], width=0.6)
            else:
                d = val - prev
                ax.bar(x, d, bottom=prev, color=t["series"][2] if d >= 0 else t["series"][1], width=0.6)
            top = val if prev is None else max(val, prev)
            ax.text(x, top, f"{val:,.1f}", ha="center", va="bottom", color=t["fg"], fontsize=9)
            prev = val
        if reference:
            ax.axhline(reference[1], color=t["series"][0], lw=1.5, ls="--")
            ax.text(
                len(steps) - 0.5,
                reference[1],
                f" {reference[0]} {reference[1]:,.1f}",
                color=t["series"][0],
                fontsize=9,
                va="bottom",
                ha="right",
            )
        ax.set_xticks(xs, [s[0] for s in steps], color=t["fg"], fontsize=8.5)
        ax.set_ylim(0, max(v for _, v in steps) * 1.12)
        ax.set_ylabel("US$ per share", color=t["muted"], fontsize=9)
        _title(ax, t, title)
        _save(fig, out, name, theme)
    return name


def forecast_vs_actual(years, fcst, actual, out: Path, name: str, title: str, unit: str) -> str:
    for theme, t in THEMES.items():
        fig, ax = plt.subplots(figsize=(8, 3.8), facecolor=t["bg"])
        _style(ax, t)
        ax.plot(years, fcst, color=t["series"][0], lw=2, ls="--", marker="o", ms=4, label="Forecast, Oct 2020")
        ax.plot(years, actual, color=t["fg"], lw=2.2, marker="o", ms=4, label="Reported")
        ax.legend(frameon=False, labelcolor=t["fg"], fontsize=9, loc="upper left")
        ax.set_ylabel(unit, color=t["muted"], fontsize=9)
        _title(ax, t, title)
        _save(fig, out, name, theme)
    return name
