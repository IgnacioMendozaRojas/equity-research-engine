"""Run a full valuation for one company and one valuation date."""

from __future__ import annotations

import copy
import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..data.store import Company
from ..model import calibrate
from ..model.projection import Projection, project
from . import dcf, montecarlo, rim
from . import wacc as waccmod


@dataclass
class Valuation:
    company: Company
    assumptions: dict
    valuation_date: dt.date
    projection: Projection
    wacc: waccmod.Wacc
    bridge: dcf.Bridge
    dcf: dcf.DcfResult
    rim: rim.RimResult
    shares: float
    price_local: float
    fx: float
    target_usd: float
    target_local: float
    upside: float
    rating: str
    weights: dict[str, float]
    mistakes: pd.DataFrame | None = None
    scenarios: pd.DataFrame | None = None
    sensitivity: dict[str, pd.DataFrame] = field(default_factory=dict)
    simulation: dict | None = None

    @property
    def price_usd(self) -> float:
        return self.price_local / self.fx


def _date(x) -> dt.date:
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x))


def base_revenue(company: Company, year: int) -> dict[str, float]:
    s = company.segments
    return s[s["year"] == year].set_index("segment")["revenue"].to_dict()


def bridge_from(company: Company, a: dict) -> dcf.Bridge:
    y = int(a["balance_year"])
    f = company.financials
    get = lambda c: float(np.nan_to_num(f.loc[c, y]))  # noqa: E731
    b = a.get("bridge", {})
    return dcf.Bridge(
        cash=b.get("cash", get("CashAndCashEquivalents")),
        other_financial_assets=b.get("other_financial_assets", get("OtherCurrentFinancialAssets")),
        debt=b.get("debt", get("OtherCurrentFinancialLiabilities") + get("OtherNoncurrentFinancialLiabilities")),
        minority_interest=b.get("minority_interest", get("NoncontrollingInterests")),
        other=b.get("other", 0.0),
        as_of=f"{y}-12-31",
        flows_from=_date(a["cash_flows_from"]) if "cash_flows_from" in a else None,
    )


def group_weights(proj: Projection, groups: dict[str, str], years: int = 10) -> dict[str, float]:
    """Share of EBITDA (company's economic share) over the first `years` by beta group."""
    w: dict[str, float] = {}
    for name, seg in proj.segments.items():
        e = (seg["ebitda"][0] * seg["weight"][0])[:years].sum()
        w[groups.get(name, "other")] = w.get(groups.get(name, "other"), 0.0) + max(e, 0.0)
    return w


def rate_bands(upside: float, bands: dict) -> str:
    if upside >= bands.get("buy", 0.15):
        return "BUY"
    if upside <= bands.get("sell", -0.15):
        return "SELL"
    return "HOLD"


def run(
    company: Company,
    valuation_date: str,
    sims: int = 0,
    overrides: dict | None = None,
    with_tables: bool = True,
) -> Valuation:
    a = copy.deepcopy(company.assumptions[valuation_date])
    if overrides:
        _deep_update(a, overrides)
    vdate = _date(a["valuation_date"])
    base = base_revenue(company, int(a["first_year"]) - 1)
    proj = project(a, base)

    d = a["discount"]
    w = waccmod.from_assumptions(d, a["tax_rate"], group_weights(proj, a["beta_groups"]))
    rate = d.get("override", w.value)
    bridge = bridge_from(company, a)
    shares = float(a["shares"])
    dres = dcf.value(proj, rate, vdate, bridge, shares)

    f = company.financials
    by = int(a["balance_year"])
    r = rim.value(
        proj,
        w.cost_of_equity,
        vdate,
        book_value=float(f.loc["Equity", by]),
        net_debt=bridge.net_debt,
        cost_of_debt=w.cost_of_debt_pretax,
        tax_rate=a["tax_rate"],
        shares=shares,
        omega=a.get("rim_omega", 0.6),
        minority_interest=bridge.minority_interest,
        flows_from=bridge.flows_from,
    )

    weights = a.get("weights", {"dcf": 0.7, "rim": 0.3})
    target_usd = weights["dcf"] * float(dres.per_share[0]) + weights["rim"] * float(r.per_share[0])
    fx = float(a.get("fx", 1.0))
    price_local = float(a["share_price"])
    target_local = target_usd * fx
    upside = target_local / price_local - 1
    rating = rate_bands(upside, a.get("rating_bands", {}))

    v = Valuation(
        company,
        a,
        vdate,
        proj,
        w,
        bridge,
        dres,
        r,
        shares,
        price_local,
        fx,
        target_usd,
        target_local,
        upside,
        rating,
        weights,
    )
    if with_tables:
        v.mistakes = mistakes_table(proj, rate, vdate, bridge, shares)
        v.scenarios = scenarios_table(company, valuation_date, a)
        v.sensitivity = sensitivity_tables(company, valuation_date, a, rate)
    if sims:
        v.simulation = simulate(company, a, proj, rate, vdate, bridge, shares, sims, v.price_usd)
    return v


def _deep_update(base: dict, upd: dict) -> None:
    for k, val in upd.items():
        if isinstance(val, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], val)
        else:
            base[k] = val


def mistakes_table(proj, rate, vdate, bridge, shares) -> pd.DataFrame:
    rows = []
    base = float(dcf.value(proj, rate, vdate, bridge, shares).per_share[0])
    cases = {
        "Correct model": dcf.Mistakes(),
        "Perpetuity on the finite lithium concession": dcf.Mistakes(perpetuity_on_finite_segments=True),
        "Terminal value discounted mid-year": dcf.Mistakes(terminal_discounted_mid_year=True),
        "Cash left out of the equity bridge": dcf.Mistakes(cash_left_out_of_bridge=True),
    }
    for label, m in cases.items():
        ps = float(dcf.value(proj, rate, vdate, bridge, shares, m).per_share[0])
        rows.append({"case": label, "value_per_share": ps, "vs_correct": ps / base - 1})
    return pd.DataFrame(rows)


def scenarios_table(company: Company, valuation_date: str, a: dict) -> pd.DataFrame:
    rows = []
    for name, ov in a.get("scenarios", {}).items():
        v = run(company, valuation_date, overrides=ov, with_tables=False)
        rows.append(
            {
                "scenario": name,
                "target_usd": v.target_usd,
                "target_local": v.target_local,
                "upside": v.upside,
                "rating": v.rating,
                "description": ov.get("_description", "") if isinstance(ov, dict) else "",
            }
        )
    return pd.DataFrame(rows)


def sensitivity_tables(company: Company, valuation_date: str, a: dict, rate: float) -> dict[str, pd.DataFrame]:
    """DCF value per share (US$) across discount rate x long-run lithium price (or terminal growth)."""
    out = {}
    vdate = _date(a["valuation_date"])
    bridge = bridge_from(company, a)
    base = base_revenue(company, int(a["first_year"]) - 1)
    rates = [rate - 0.01, rate - 0.005, rate, rate + 0.005, rate + 0.01]
    key = a.get("sensitivity_segment")
    if key:
        lr = a["segments"][key]["price"]
        last = max(int(k) for k in lr)
        levels = [0.7, 0.85, 1.0, 1.15, 1.3]
        table = {}
        for m in levels:
            b = copy.deepcopy(a)
            b["segments"][key]["price"] = {k: (v * m if int(k) >= last else v) for k, v in lr.items()}
            p = project(b, base)
            table[f"{lr[last] * m:,.0f}"] = [
                float(dcf.value(p, r, vdate, bridge, float(a["shares"])).per_share[0]) for r in rates
            ]
        out["rate_x_long_run_price"] = pd.DataFrame(table, index=[f"{r:.2%}" for r in rates])
    p = project(a, base)
    table = {}
    for g in [0.0, 0.01, 0.02, 0.03]:
        for s in p.terminal.values():
            if s["method"] == "gordon":
                s["growth"] = g
        table[f"{g:.0%}"] = [float(dcf.value(p, r, vdate, bridge, float(a["shares"])).per_share[0]) for r in rates]
    out["rate_x_terminal_growth"] = pd.DataFrame(table, index=[f"{r:.2%}" for r in rates])
    return out


def simulate(company, a, proj, rate, vdate, bridge, shares, sims, price_usd) -> dict:
    mc = a.get("montecarlo", {})
    names = mc.get("segments", [])
    deck = {k: proj.segments[k]["price"][0] for k in names}
    hist_until = int(a["first_year"]) - 1
    sigma = {k: mc.get("sigma", {}).get(k) or calibrate.price_volatility(company, k, until=hist_until) for k in names}
    paths = montecarlo.mean_reverting_paths(deck, sigma, phi=mc.get("phi", 0.7), n=sims, seed=mc.get("seed", 7))
    p = project(a, base_revenue(company, hist_until), price_override=paths)
    values = dcf.value(p, rate, vdate, bridge, shares).per_share
    return {
        "values": values,
        "sigma": sigma,
        "phi": mc.get("phi", 0.7),
        "summary": montecarlo.summary(values, price_usd),
        "paths": paths,
    }


def implied_long_run_price(company: Company, valuation_date: str, target_usd: float | None = None) -> float:
    """Long-run price of the sensitivity segment at which the target equals the share price.

    Answers "what lithium price is the market paying for?". Scales the deck from its
    last key year onward and solves for the blended (DCF + RIM) value.
    """
    from scipy.optimize import brentq

    a = company.assumptions[valuation_date]
    key = a["sensitivity_segment"]
    deck = a["segments"][key]["price"]
    last = max(int(k) for k in deck)
    target = target_usd if target_usd is not None else a["share_price"] / a.get("fx", 1.0)

    def gap(m: float) -> float:
        ov = {"segments": {key: {"price": {k: (v * m if int(k) >= last else v) for k, v in deck.items()}}}}
        return run(company, valuation_date, overrides=ov, with_tables=False).target_usd - target

    m = brentq(gap, 0.2, 6.0, xtol=1e-4)
    return float(deck[last] * m) if last in deck else float(deck[str(last)] * m)
