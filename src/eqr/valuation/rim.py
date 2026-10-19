"""Residual income model, consistent with the DCF.

Earnings come from the same projection (NOPAT less after-tax interest on a
constant net debt load) and the cost of equity is the DCF's. Book value follows clean
surplus with all free cash flow to equity paid out, so book value grows exactly by
net investment (capex - depreciation + working capital). That is the payout the DCF
implicitly assumes; any other payout would need an assumption about what retained
cash earns. Beyond the horizon residual income fades at persistence `omega`
(0 = vanishes at once, 1 = a perpetuity), which avoids the arbitrary terminal cost
of equity and growth rate a RIM often ends up with.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from ..model.projection import Projection
from .dcf import timing


@dataclass
class RimResult:
    equity: np.ndarray
    per_share: np.ndarray
    book_value: float
    pv_residual_income: np.ndarray
    net_income: np.ndarray
    residual_income: np.ndarray


def value(
    proj: Projection,
    cost_of_equity: float,
    valuation_date: dt.date,
    book_value: float,
    net_debt: float,
    cost_of_debt: float,
    tax_rate: float,
    shares: float,
    omega: float = 0.6,
    minority_interest: float = 0.0,
    flows_from: dt.date | None = None,
) -> RimResult:
    frac, mid, t_end = timing(proj.years, valuation_date, flows_from)
    after_tax_interest = net_debt * cost_of_debt * (1 - tax_rate)
    net_income = proj.total("nopat") - after_tax_interest
    fcfe = proj.total("fcf") - after_tax_interest
    n, T = net_income.shape
    bv = np.full(n, book_value - minority_interest)
    ri = np.zeros_like(net_income)
    for t in range(T):
        ri[:, t] = net_income[:, t] - cost_of_equity * bv
        bv = bv + (net_income[:, t] - fcfe[:, t]) * frac[t]
    disc = (1 + cost_of_equity) ** -mid
    pv = (ri * frac * disc).sum(axis=1)
    fade = ri[:, -1] * omega / (1 + cost_of_equity - omega) * (1 + cost_of_equity) ** -t_end
    equity = book_value - minority_interest + pv + fade
    return RimResult(equity, equity / shares, book_value, pv + fade, net_income, ri)
