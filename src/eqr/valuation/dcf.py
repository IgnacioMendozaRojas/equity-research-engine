"""Discounted cash flow and the enterprise-to-equity bridge.

Timing: cash flows arrive mid-year (or mid-way through the stub left in the
valuation year). The terminal value is a value *at the end* of the last projected
year and is discounted from there, not from mid-year.

Bridge: equity = EV + cash + other current financial assets - financial debt -
minority interests. Cash that the projection treats as non-operating has to come
back here; leaving it out undervalues the equity by the whole cash pile.

`Mistakes` switches reproduce common errors so their effect can be measured:
perpetuity on finite assets, terminal value discounted mid-year, cash left out of
the bridge.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np

from ..model.projection import Projection


@dataclass(frozen=True)
class Bridge:
    cash: float
    other_financial_assets: float
    debt: float
    minority_interest: float = 0.0
    other: float = 0.0  # e.g. equity-method investments, provisions (signed)
    as_of: str = ""
    flows_from: dt.date | None = None  # count cash flows from this date (balance sheet date)

    @property
    def net_debt(self) -> float:
        return self.debt - self.cash - self.other_financial_assets

    def equity(self, ev: np.ndarray, include_cash: bool = True) -> np.ndarray:
        cash = self.cash + self.other_financial_assets if include_cash else 0.0
        return ev + cash - self.debt - self.minority_interest + self.other


@dataclass(frozen=True)
class Mistakes:
    perpetuity_on_finite_segments: bool = False
    terminal_discounted_mid_year: bool = False
    cash_left_out_of_bridge: bool = False


@dataclass
class DcfResult:
    ev: np.ndarray
    pv_explicit: np.ndarray
    pv_terminal: np.ndarray
    equity: np.ndarray
    per_share: np.ndarray
    by_segment: dict[str, np.ndarray] = field(default_factory=dict)
    discount_factors: np.ndarray | None = None
    year_fraction: np.ndarray | None = None

    @property
    def terminal_share(self) -> float:
        return float(np.mean(self.pv_terminal) / np.mean(self.ev))


def timing(
    years: np.ndarray, valuation_date: dt.date, flows_from: dt.date | None = None
) -> tuple[np.ndarray, np.ndarray, float]:
    """(fraction of each year counted, mid-point time in years, time to end of horizon).

    Cash flows are counted from `flows_from` (default: the valuation date). Set it to
    the date of the balance sheet used in the bridge, so cash generated after that
    date and not yet in the reported cash is not lost; those flows get a small
    negative time and are compounded to the valuation date.
    """
    flows_from = flows_from or valuation_date
    frac, mid = [], []
    for y in years:
        start, end = dt.date(int(y), 1, 1), dt.date(int(y), 12, 31)
        lo = max(start, flows_from)
        f = max((end - lo).days + 1, 0) / ((end - start).days + 1)
        frac.append(f)
        mid.append(((lo - valuation_date).days + f * ((end - start).days + 1) / 2) / 365.25)
    t_end = (dt.date(int(years[-1]), 12, 31) - valuation_date).days / 365.25
    return np.array(frac), np.array(mid), t_end


def value(
    proj: Projection,
    rate: float,
    valuation_date: dt.date,
    bridge: Bridge,
    shares: float,
    mistakes: Mistakes | None = None,
    flows_from: dt.date | None = None,
) -> DcfResult:
    mistakes = mistakes or Mistakes()
    frac, mid, t_end = timing(proj.years, valuation_date, flows_from or bridge.flows_from)
    disc = (1 + rate) ** -mid
    t_tv = mid[-1] if mistakes.terminal_discounted_mid_year else t_end
    pv_exp_total, pv_tv_total, by_seg = 0.0, 0.0, {}
    for name, seg in proj.segments.items():
        fcf = seg["fcf"]
        pv_exp = (fcf * frac * disc).sum(axis=1)
        term = proj.terminal[name]
        last_fcf = fcf[:, -1]
        if mistakes.perpetuity_on_finite_segments and term["method"] == "none":
            # what a Gordon model on the last *active* year would have assumed
            active = np.nonzero(seg["weight"][0] > 0)[0]
            last_fcf = fcf[:, active[-1]] if active.size else last_fcf
            t_tv_seg = (mid[active[-1]] + 0.5) if active.size else t_tv
            pv_tv = last_fcf * (1 + term["growth"]) / (rate - term["growth"]) * (1 + rate) ** -t_tv_seg
        elif term["method"] == "gordon":
            g = term["growth"]
            if g >= rate:
                raise ValueError(f"terminal growth {g:.2%} must be below the discount rate {rate:.2%}")
            pv_tv = last_fcf * (1 + g) / (rate - g) * (1 + rate) ** -t_tv
        else:
            pv_tv = np.zeros_like(pv_exp)
        by_seg[name] = pv_exp + pv_tv
        pv_exp_total = pv_exp_total + pv_exp
        pv_tv_total = pv_tv_total + pv_tv
    ev = pv_exp_total + pv_tv_total
    equity = bridge.equity(ev, include_cash=not mistakes.cash_left_out_of_bridge)
    return DcfResult(ev, pv_exp_total, pv_tv_total, equity, equity / shares, by_seg, disc, frac)
