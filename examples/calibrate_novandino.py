"""Calibrate SQM's share of Nova Andino's operating margin to reported 1H2026 earnings.

The public terms of the SQM-Codelco agreement give the state's take only as a
headline (about 70% of the operating margin to 2030). This script runs the 2026
model at the 1H2026 run-rate (volumes and prices from the 2Q2026 release, doubled)
and finds the lithium margin share at which modelled net income matches the
reported US$1,024.7m attributable net income for the half, doubled.

    python examples/calibrate_novandino.py
"""

from __future__ import annotations

import copy
from pathlib import Path

from scipy.optimize import brentq

from eqr.data.store import load_company
from eqr.model.projection import project
from eqr.valuation import engine

ROOT = Path(__file__).resolve().parents[1]
REPORTED_NET_INCOME = 2 * 1024.7  # US$ m, 1H2026 attributable, annualised

# 1H2026 run-rate: (volume kt for the half, revenue US$ m for the half), 2Q2026 release
RUN_RATE = {
    "lithium": (138.2, 2764.7),
    "lithium_intl": (86.1, 200.1),
    "iodine": (7.9, 578.1),
    "spn": (535.3, 562.0),
    "potassium": (148.9, 75.6),
}


def modelled_net_income(share: float) -> float:
    company = load_company(ROOT / "companies" / "sqm")
    a = copy.deepcopy(company.assumptions["2026-10-16"])
    a["horizon"] = a["first_year"]
    for name, (vol, rev) in RUN_RATE.items():
        a["segments"][name]["volume"] = {2026: 2 * vol}
        a["segments"][name]["price"] = {2026: rev / vol * 1000}
    a["segments"]["lithium"]["regimes"][0]["share"] = share
    p = project(a, engine.base_revenue(company, 2025))
    bridge = engine.bridge_from(company, a)
    w = engine.run(company, "2026-10-16", with_tables=False).wacc
    interest = bridge.net_debt * w.cost_of_debt_pretax * (1 - a["tax_rate"])
    return float(p.total("nopat")[0, 0] - interest)


if __name__ == "__main__":
    implied = brentq(lambda s: modelled_net_income(s) - REPORTED_NET_INCOME, 0.05, 0.95)
    for s in (0.30, implied, 0.50):
        print(
            f"share {s:.2f}: modelled net income {modelled_net_income(s):,.0f} vs reported {REPORTED_NET_INCOME:,.0f}"
        )
    print(f"implied 2026-2030 share of Nova Andino's operating margin: {implied:.1%}")
