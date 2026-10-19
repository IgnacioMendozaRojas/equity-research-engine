"""Hold a past valuation against what happened next.

Two views:

1. Forecast vs actual for the years that have since been reported.
2. A value walk: re-run the past model replacing one assumption at a time with what
   actually happened (prices, volumes, the fiscal regime), so the gap between the
   past target and the realised share price is attributed to its causes.
"""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from ..data.store import Company
from ..model import calibrate
from ..model.projection import project
from . import dcf, engine


def forecast_vs_actual(company: Company, valuation_date: str) -> pd.DataFrame:
    v = engine.run(company, valuation_date, with_tables=False)
    p = v.projection
    seg = calibrate.segment_history(company)
    li = seg[seg["segment"] == "lithium"].set_index("year")
    ebitda = calibrate.ebitda(company)
    f = company.financials
    rows = []
    for i, y in enumerate(p.years):
        if y not in f.columns:
            continue
        rows.append(
            {
                "year": int(y),
                "lithium_volume_fcst": p.segments["lithium"]["volume"][0, i],
                "lithium_volume_actual": li.loc[y, "volume"] if y in li.index else np.nan,
                "lithium_price_fcst": p.segments["lithium"]["price"][0, i],
                "lithium_price_actual": li.loc[y, "price"] if y in li.index else np.nan,
                "revenue_fcst": p.total("revenue")[0, i],
                "revenue_actual": f.loc["Revenue", y],
                "ebitda_fcst": p.total("ebitda")[0, i],
                "ebitda_actual": ebitda[y],
                "capex_fcst": p.total("capex")[0, i],
                "capex_actual": f.loc["PurchaseOfPPE", y],
            }
        )
    return pd.DataFrame(rows).set_index("year")


def _actual_paths(company: Company, a: dict, years: np.ndarray) -> tuple[dict, dict]:
    """Model price/volume paths with reported years swapped in."""
    seg = calibrate.segment_history(company)
    base = project(a)
    prices, volumes = {}, {}
    for name in a["segments"]:
        hist = seg[seg["segment"] == name].set_index("year")
        if hist.empty or name == "other":
            continue
        pr = base.segments[name]["price"][0].copy()
        vo = base.segments[name]["volume"][0].copy()
        for i, y in enumerate(years):
            if y in hist.index and not np.isnan(hist.loc[y, "price"]):
                pr[i], vo[i] = hist.loc[y, "price"], hist.loc[y, "volume"]
        prices[name], volumes[name] = pr, vo
    return prices, volumes


def value_walk(company: Company, valuation_date: str, regime_update: dict | None = None) -> pd.DataFrame:
    """DCF value per share (US$) as hindsight is added step by step."""
    v = engine.run(company, valuation_date, with_tables=False)
    a = v.assumptions
    rate = v.wacc.value
    years = v.projection.years
    base_rev = engine.base_revenue(company, int(a["first_year"]) - 1)
    prices, volumes = _actual_paths(company, a, years)

    def val(assump, price_ov=None, vol_ov=None) -> float:
        p = project(assump, base_rev, price_override=price_ov, volume_override=vol_ov)
        return float(dcf.value(p, rate, v.valuation_date, v.bridge, v.shares).per_share[0])

    steps = [("Model in " + str(v.valuation_date.year), val(a))]
    li_only = {"lithium": prices["lithium"]}
    steps.append(("+ actual lithium prices to date", val(a, li_only)))
    steps.append(("+ actual prices and volumes, all segments", val(a, prices, volumes)))

    # actual capex: the gap to the model's capex is booked on the growth segment
    b = copy.deepcopy(a)
    base_capex = project(a, base_rev, prices, volumes).total("capex")[0]
    f = company.financials
    extra = {
        int(y): float(f.loc["PurchaseOfPPE", y] - base_capex[i])
        for i, y in enumerate(years)
        if y in f.columns and not np.isnan(f.loc["PurchaseOfPPE", y])
    }
    growth = a.get("sensitivity_segment", next(iter(a["segments"])))
    b["segments"][growth]["capex"] = {**b["segments"][growth].get("capex", {}), **extra}
    steps.append(("+ actual capex", val(b, prices, volumes)))
    if regime_update:
        for name, regimes in regime_update.items():  # applied on top of actual capex
            b["segments"][name]["regimes"] = regimes
        steps.append(("+ Codelco agreement (state take 2025-2060)", val(b, prices, volumes)))
    out = pd.DataFrame(steps, columns=["step", "value_per_share"])
    out["change"] = out["value_per_share"].diff()
    return out
