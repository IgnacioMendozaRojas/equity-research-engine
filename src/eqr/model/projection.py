"""Segment-driven projection.

Every business line is projected as volume x price, with its own cost structure,
capital spending and fiscal regime, then summed. Arrays have shape (n, T): `n`
price scenarios (1 for the deterministic case, thousands for Monte Carlo) by `T`
years, so the same code serves the base case, scenarios and simulation.

Units: volumes in thousand tonnes, prices in US$/t, money in US$ millions.

Fiscal regimes
--------------
corporate      cash flow = EBIT x (1 - tax) + D&A - capex - change in working capital
margin_share   the company keeps a share of the operating margin; the rest is the
               state's take (taxes, lease payments, levies and a state partner's
               profits), so lease payments and levies are added back before sharing:
               cash flow = share x (EBITDA + lease + levies - capex - change in NWC)

A regime can carry a probability (e.g. a concession renewal that may not happen);
cash flows in that period are weighted by it. Years outside every regime produce
nothing: the segment has ended. That is how a finite concession is valued without
a perpetuity.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import royalty as roy

BRACKETS = {
    "corfo_lithium_carbonate": roy.CORFO_LITHIUM_CARBONATE,
    "corfo_potassium_chloride": roy.CORFO_POTASSIUM_CHLORIDE,
}
ITEMS = (
    "volume",
    "price",
    "revenue",
    "cash_cost",
    "royalty",
    "levies",
    "admin",
    "ebitda",
    "capex",
    "depreciation",
    "ebit",
    "delta_nwc",
    "tax",
    "nopat",
    "fcf",
    "weight",
)


def path(spec: dict | float | int, years: np.ndarray, growth: float = 0.0) -> np.ndarray:
    """Year -> value map extended beyond its last year at `growth` per year.

    Years before the first key take the first value.
    """
    if not isinstance(spec, dict):
        return np.full(years.shape, float(spec))
    keys = sorted(int(k) for k in spec)
    vals = {int(k): float(v) for k, v in spec.items()}
    out = np.empty(years.shape)
    for i, y in enumerate(years):
        if y in vals:
            out[i] = vals[y]
        elif y < keys[0]:
            out[i] = vals[keys[0]]
        elif y > keys[-1]:
            out[i] = vals[keys[-1]] * (1 + growth) ** (y - keys[-1])
        else:  # gap between keys: linear interpolation
            lo = max(k for k in keys if k < y)
            hi = min(k for k in keys if k > y)
            w = (y - lo) / (hi - lo)
            out[i] = vals[lo] * (1 - w) + vals[hi] * w
    return out


def regime_arrays(regimes: list[dict] | None, years: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-year (is_margin_share, share, probability). Probability 0 = segment inactive."""
    kind = np.zeros(years.shape, dtype=bool)
    share = np.ones(years.shape)
    prob = np.zeros(years.shape) if regimes else np.ones(years.shape)
    for r in regimes or []:
        lo, hi = int(r.get("from", years[0])), int(r.get("to", years[-1]))
        m = (years >= lo) & (years <= hi)
        kind[m] = r["type"] == "margin_share"
        share[m] = float(r.get("share", 1.0))
        prob[m] = float(r.get("probability", 1.0))
    return kind, share, prob


@dataclass
class Projection:
    years: np.ndarray
    segments: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    terminal: dict[str, dict] = field(default_factory=dict)

    def total(self, item: str) -> np.ndarray:
        return sum(s[item] for s in self.segments.values())

    def deterministic(self, item: str) -> dict[str, np.ndarray]:
        """Segment -> first scenario path, handy for tables."""
        return {k: v[item][0] for k, v in self.segments.items()}


def project(
    assumptions: dict,
    base_revenue: dict[str, float] | None = None,
    price_override: dict[str, np.ndarray] | None = None,
    volume_override: dict[str, np.ndarray] | None = None,
) -> Projection:
    """Run the projection. Overrides replace a segment's price/volume path (shape (n, T) or (T,))."""
    a = assumptions
    years = np.arange(int(a["first_year"]), int(a["horizon"]) + 1)
    infl = float(a.get("inflation", 0.0))
    tax = float(a["tax_rate"])
    admin_pct = float(a.get("admin_pct_revenue", 0.0))
    # working capital: receivables follow revenue; inventories and payables follow cash
    # costs, so a price spike does not pretend the company stocked up at the new price
    rec_pct = float(a.get("receivables_pct_revenue", 0.0))
    inv_pct = float(a.get("inventory_pct_cost", 0.0))
    pay_pct = float(a.get("payables_pct_cost", 0.0))
    dep_rate = float(a["depreciation_rate"])
    opening_ppe = float(a["opening_ppe"])
    base_revenue = base_revenue or {}

    specs = a["segments"]
    ppe_shares = {k: float(v.get("ppe_share", 0.0)) for k, v in specs.items()}
    if not any(ppe_shares.values()):
        ppe_shares = {k: 1 / len(specs) for k in specs}

    price_override = price_override or {}
    volume_override = volume_override or {}
    n = max([np.atleast_2d(v).shape[0] for v in [*price_override.values(), *volume_override.values()]] or [1])
    proj = Projection(years)

    for name, s in specs.items():
        volume = np.atleast_2d(volume_override.get(name, path(s["volume"], years, s.get("volume_growth", 0.0))))
        price = np.atleast_2d(price_override.get(name, path(s["price"], years, s.get("price_growth", infl))))
        volume, price = np.broadcast_to(volume, (n, len(years))), np.broadcast_to(price, (n, len(years)))
        revenue = volume * price / 1_000

        if "cash_cost_per_t" in s:
            esc = (1 + infl) ** (years - int(s.get("cost_base_year", years[0])))
            cash_cost = volume * float(s["cash_cost_per_t"]) * esc / 1_000
        else:
            cash_cost = revenue * (1 - float(s["cash_margin"]))

        royalty = np.zeros_like(revenue)
        if "royalty" in s:
            r = s["royalty"]
            brackets = BRACKETS[r["brackets"]] if isinstance(r["brackets"], str) else r["brackets"]
            active = years <= int(r.get("until", years[-1]))
            royalty = volume * roy.bracket_payment(price, brackets) / 1_000 * active

        levies = np.zeros_like(revenue)
        for lev in s.get("levies", []):
            active = years <= int(lev.get("until", years[-1]))
            levies = levies + revenue * float(lev.get("pct_revenue", 0.0)) * active
            levies = levies + float(lev.get("fixed", 0.0)) * (1 + infl) ** (years - years[0]) * active

        admin = revenue * admin_pct
        ebitda = revenue - cash_cost - royalty - levies - admin

        capex = revenue * float(s.get("maintenance_capex_pct", 0.0))
        if "capacity" in s:
            cap = path(s["capacity"], np.append(years, years[-1] + 1))
            build = np.clip(np.diff(cap), 0, None)  # capacity added next year, paid this year
            capex = capex + build * float(s["expansion_cost_per_t"]) / 1_000 * (1 + infl) ** (years - years[0])
        if "capex" in s:  # explicit project capex (US$ m), e.g. a disclosed plan
            plan = {int(k): float(v) for k, v in s["capex"].items()}
            capex = capex + np.array([plan.get(int(y), 0.0) for y in years])

        kind, share, prob = regime_arrays(s.get("regimes"), years)

        depreciation = np.zeros_like(revenue)
        ppe = np.full(n, opening_ppe * ppe_shares[name])
        for t in range(len(years)):
            depreciation[:, t] = dep_rate * ppe
            ppe = ppe + capex[:, t] - depreciation[:, t]
        ebit = ebitda - depreciation

        nwc = rec_pct * revenue + (inv_pct - pay_pct) * cash_cost
        scale = base_revenue.get(name, revenue[0, 0]) / np.where(revenue[:, :1] > 0, revenue[:, :1], 1.0)
        opening = nwc[:, :1] * scale  # base-year NWC at the first year's cost structure
        delta_nwc = nwc - np.concatenate([opening, nwc[:, :-1]], axis=1)

        corp_tax = tax * ebit
        corp_fcf = ebit - corp_tax + depreciation - capex - delta_nwc
        # the state's take already includes lease payments and levies: share the pre-take margin
        state_items = royalty + levies
        ms_fcf = share * (ebitda + state_items - capex - delta_nwc)
        fcf = np.where(kind, ms_fcf, corp_fcf) * prob
        nopat = np.where(kind, share * (ebit + state_items), ebit - corp_tax) * prob
        tax_paid = np.where(kind, 0.0, corp_tax) * prob

        proj.segments[name] = {
            "volume": volume,
            "price": price,
            "revenue": revenue,
            "cash_cost": cash_cost,
            "royalty": royalty,
            "levies": levies,
            "admin": admin,
            "ebitda": ebitda,
            "capex": capex,
            "depreciation": depreciation,
            "ebit": ebit,
            "delta_nwc": delta_nwc,
            "tax": tax_paid,
            "nopat": nopat,
            "fcf": fcf,
            "weight": np.broadcast_to(prob * np.where(kind, share, 1.0), (n, len(years))),
        }
        proj.terminal[name] = {
            "method": s.get("terminal", "gordon"),
            "growth": float(s.get("terminal_growth", a.get("terminal_growth", infl))),
        }
    return proj
