"""Shared chart style for Ignacio Mendoza Rojas's repositories (same file in each repo).

Conventions
-----------
- The title states the finding, not the topic ("A zero-threshold CSA cuts peak PFE by 70%"),
  the subtitle says what is plotted and in which unit, and the footer gives source and method.
- The analytical step is drawn on the chart (an event, a threshold, the effect of a
  decision) with a short note and a leader line, not left to the text.
- One categorical palette, assigned in fixed order; series are labelled directly at their
  end and listed in a legend when there are two or more.
- Every chart is saved twice, for light and dark backgrounds (<name>-light.png / -dark.png).
- Thin marks (2 px lines), recessive 1 px grid, text in ink colours, never in series colours.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "text": "#0b0b0b",
        "muted": "#52514e",
        "grid": "#e4e3df",
        "accent": "#0b0b0b",
        "series": [
            "#2a78d6",
            "#eb6834",
            "#1baf7a",
            "#eda100",
            "#e87ba4",
            "#008300",
            "#6250d6",
            "#e34948",
        ],
    },
    "dark": {
        "surface": "#1a1a19",
        "text": "#f0efec",
        "muted": "#c3c2b7",
        "grid": "#34332f",
        "accent": "#f0efec",
        "series": [
            "#3987e5",
            "#d95926",
            "#199e70",
            "#c98500",
            "#d55181",
            "#008300",
            "#9085e9",
            "#e66767",
        ],
    },
}
FONT = "DejaVu Sans"  # available on every CI runner, so local and automated figures match


class Chart:
    """One figure, drawn once per theme: `for c in charts(...): c.ax.plot(...)`."""

    def __init__(self, theme: str, title: str, subtitle: str, source: str, size=(9, 4.8)):
        self.mode, self.t = theme, THEMES[theme]
        plt.rcParams["font.family"] = FONT
        plt.rcParams["text.parse_math"] = False  # "US$" in titles must stay text
        self.fig, self.ax = plt.subplots(figsize=size, dpi=150)
        t, ax = self.t, self.ax
        self.fig.patch.set_facecolor(t["surface"])
        ax.set_facecolor(t["surface"])
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(t["grid"])
        ax.tick_params(colors=t["muted"], labelsize=9, length=0, pad=6)
        ax.grid(axis="y", color=t["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
        self.fig.text(0.06, 0.955, title, color=t["text"], fontsize=13, weight="bold", va="top")
        self.fig.text(0.06, 0.885, subtitle, color=t["muted"], fontsize=9.5, va="top")
        import textwrap

        self.fig.text(
            0.06,
            0.015,
            "\n".join(textwrap.wrap(source, 150)),
            color=t["muted"],
            fontsize=7.5,
            va="bottom",
            linespacing=1.4,
        )
        self.fig.subplots_adjust(left=0.08, right=0.84, top=0.80, bottom=0.2)

    def color(self, i: int) -> str:
        return self.t["series"][i]

    # ── marks ──────────────────────────────────────────────────────────
    def line(self, x, y, i: int, label: str, end_label: bool = True, dy: float = 0, label_x=None, **kw):
        """A 2 px series line, labelled at its end (or at `label_x`, offset `dy` points)."""
        import numpy as np

        self.ax.plot(x, y, color=self.color(i), linewidth=2, solid_capstyle="round", label=label, **kw)
        if not end_label:
            return
        k = len(x) - 1 if label_x is None else int(np.argmin(np.abs(np.asarray(x) - label_x)))
        self.ax.annotate(
            f" {label}",
            (x[k], y[k]),
            xytext=(4 if label_x is None else 0, dy),
            textcoords="offset points",
            color=self.t["text"],
            fontsize=8.5,
            va="center",
            ha="left" if label_x is None else "center",
            annotation_clip=False,
        )

    def stack(self, x, columns: dict, labels: bool = True):
        """Stacked areas in palette order, separated by a surface-colour gap, labelled at the right end."""
        names = list(columns)
        self.ax.stackplot(
            x,
            *[columns[n] for n in names],
            colors=self.t["series"][: len(names)],
            edgecolor=self.t["surface"],
            linewidth=1.0,
            labels=names,
        )
        if labels:
            base = 0.0
            for n in names:
                v = float(columns[n][-1])
                self.ax.annotate(
                    f" {n}",
                    (x[-1], base + v / 2),
                    xytext=(4, 0),
                    textcoords="offset points",
                    fontsize=8.5,
                    color=self.t["text"],
                    va="center",
                    annotation_clip=False,
                )
                base += v
        self.ax.set_xlim(x[0], x[-1])

    def hbars(self, labels, values, fmt="{:,.0f}", highlight: set | None = None, sort: bool = True):
        """Horizontal bars, largest on top (or in the given order), value at the tip; highlighted bars in slot 1."""
        pairs = list(zip(labels, values, strict=True))
        pairs = sorted(pairs, key=lambda p: p[1]) if sort else pairs[::-1]
        ys = range(len(pairs))
        colors = [self.color(0) if highlight is None or lab in highlight else self.t["grid"] for lab, _ in pairs]
        self.ax.barh(list(ys), [v for _, v in pairs], color=colors, height=0.6)
        self.ax.set_yticks(list(ys), [lab for lab, _ in pairs], color=self.t["text"])
        for y, (_, v) in zip(ys, pairs, strict=True):
            self.ax.annotate(
                fmt.format(v),
                (v, y),
                xytext=(4, 0),
                textcoords="offset points",
                va="center",
                fontsize=8.5,
                color=self.t["text"],
            )
        self.ax.grid(False)
        self.ax.grid(axis="x", color=self.t["grid"], linewidth=0.8)

    # ── the analytical step ───────────────────────────────────────────
    def note(self, xy, text: str, xytext=(30, 30)):
        """A finding pinned to a point, with a thin leader line."""
        self.ax.annotate(
            text,
            xy,
            xytext=xytext,
            textcoords="offset points",
            fontsize=8.5,
            color=self.t["text"],
            arrowprops={"arrowstyle": "-", "color": self.t["muted"], "linewidth": 0.8},
            annotation_clip=False,
        )

    def event(self, x, label: str, y_frac: float = 0.98):
        """A dated event as a hairline with its name at the top."""
        self.ax.axvline(x, color=self.t["muted"], linewidth=0.8, linestyle=(0, (2, 2)))
        self.ax.text(
            x,
            y_frac,
            f" {label}",
            transform=self.ax.get_xaxis_transform(),
            fontsize=8,
            color=self.t["muted"],
            va="top",
        )

    def span(self, x0, x1, label: str = ""):
        """A shaded period with its name at the top left."""
        self.ax.axvspan(x0, x1, color=self.t["grid"], alpha=0.6, linewidth=0)
        if label:
            self.ax.text(
                x0,
                0.98,
                f" {label}",
                transform=self.ax.get_xaxis_transform(),
                fontsize=8,
                color=self.t["muted"],
                va="top",
            )

    # ── axes and legend ───────────────────────────────────────────────
    def yaxis(self, unit: str = "", pct: bool = False, millions: bool = False):
        if pct:
            self.ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        elif millions:
            self.ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1e6:,.0f}M"))
        if unit:
            self.ax.set_ylabel(unit, color=self.t["muted"], fontsize=9)

    def xlabel(self, text: str):
        self.ax.set_xlabel(text, color=self.t["muted"], fontsize=9)

    def legend(self, loc="upper right"):
        if len(self.ax.get_legend_handles_labels()[0]) >= 2:
            self.ax.legend(frameon=False, loc=loc, fontsize=8.5, labelcolor=self.t["text"])

    def save(self, out: Path, name: str) -> Path:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{name}-{self.mode}.png"
        self.fig.savefig(path, facecolor=self.t["surface"])
        plt.close(self.fig)
        return path


def charts(title: str, subtitle: str, source: str, size=(9, 4.8)) -> Iterator[Chart]:
    """Yield the same chart for each theme; draw on it and call .save()."""
    for mode in THEMES:
        yield Chart(mode, title, subtitle, source, size)


def picture(path_light: str, alt: str) -> str:
    """Markdown/HTML snippet that switches the image with the reader's theme on GitHub."""
    dark = path_light.replace("-light.png", "-dark.png")
    return (
        "<picture>\n"
        f'  <source media="(prefers-color-scheme: dark)" srcset="{dark}">\n'
        f'  <img alt="{alt}" src="{path_light}">\n'
        "</picture>"
    )
