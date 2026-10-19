import datetime as dt

import numpy as np
import pytest

from eqr.model.projection import path, project
from eqr.model.royalty import CORFO_LITHIUM_CARBONATE, average_rate, bracket_payment
from eqr.valuation import dcf, montecarlo, rim
from eqr.valuation.wacc import Wacc, blended_beta


@pytest.mark.parametrize(
    ("price", "expected"),
    [(0, 0), (3_000, 204), (4_000, 272), (6_000, 452), (10_000, 1_372), (12_000, 2_172)],
)
def test_corfo_lease_is_marginal(price, expected):
    assert bracket_payment(price, CORFO_LITHIUM_CARBONATE) == pytest.approx(expected)


def test_corfo_average_rate_rises_towards_40pct():
    rates = average_rate(np.array([5_000, 20_000, 200_000]), CORFO_LITHIUM_CARBONATE)
    assert np.all(np.diff(rates) > 0) and rates[-1] < 0.40


def test_path_extends_and_interpolates():
    years = np.arange(2020, 2027)
    out = path({2020: 100, 2022: 200, 2024: 400}, years, growth=0.10)
    assert out.tolist() == pytest.approx([100, 150, 200, 300, 400, 440, 484])
    assert path(5, years).tolist() == [5.0] * 7


def one_segment(**seg):
    base = {
        "first_year": 2025,
        "horizon": 2034,
        "inflation": 0.0,
        "tax_rate": 0.25,
        "depreciation_rate": 0.1,
        "opening_ppe": 0.0,
        "segments": {"a": {"volume": {2025: 10}, "price": {2025: 1000}, "cash_margin": 0.5, **seg}},
    }
    return base


def test_corporate_cash_flow():
    p = project(one_segment())
    s = p.segments["a"]
    assert s["revenue"][0, 0] == pytest.approx(10)  # 10 kt x US$1,000/t = US$10m
    assert s["fcf"][0, 0] == pytest.approx(5 * 0.75)  # no capex, no D&A, no working capital


def test_margin_share_adds_back_the_lease_and_ends_with_the_concession():
    seg = {
        "cash_cost_per_t": 400,
        "cost_base_year": 2025,
        "royalty": {"brackets": [[0, 0.1]], "until": 2034},
        "regimes": [{"from": 2025, "to": 2029, "type": "margin_share", "share": 0.3}],
        "terminal": "none",
    }
    s = project(one_segment(**seg)).segments["a"]
    margin_before_lease = 10 - 4  # revenue - cash cost
    assert s["fcf"][0, 0] == pytest.approx(0.3 * margin_before_lease)
    assert np.all(s["fcf"][0, 5:] == 0)  # 2030 onwards: concession over


def test_probability_weights_uncertain_periods():
    seg = {"regimes": [{"to": 2029, "type": "corporate"}, {"from": 2030, "type": "corporate", "probability": 0.5}]}
    s = project(one_segment(**seg)).segments["a"]
    assert s["fcf"][0, 5] == pytest.approx(0.5 * s["fcf"][0, 4])


def test_capex_follows_capacity_one_year_ahead():
    s = project(one_segment(capacity={2025: 10, 2027: 30}, expansion_cost_per_t=2000)).segments["a"]
    # +10 kt in 2026 and +10 kt in 2027, each paid the year before, at US$2,000/t = US$20m
    assert s["capex"][0, :3].tolist() == pytest.approx([20, 20, 0])


def test_dcf_matches_closed_form():
    r, f = 0.10, 3.75
    p = project(one_segment(terminal="gordon", terminal_growth=0.0))
    bridge = dcf.Bridge(cash=0, other_financial_assets=0, debt=0)
    res = dcf.value(p, r, dt.date(2025, 1, 1), bridge, shares=1)
    T = 10
    explicit = sum(f * (1 + r) ** -(t - 0.5) for t in range(1, T + 1))
    terminal = f / r * (1 + r) ** -T
    assert float(res.ev[0]) == pytest.approx(explicit + terminal, rel=2e-3)


def test_mistakes_move_value_the_right_way():
    p = project(one_segment(terminal="gordon"))
    bridge = dcf.Bridge(cash=5, other_financial_assets=1, debt=2)
    date = dt.date(2025, 1, 1)
    ok = float(dcf.value(p, 0.1, date, bridge, 1).per_share[0])
    no_cash = float(dcf.value(p, 0.1, date, bridge, 1, dcf.Mistakes(cash_left_out_of_bridge=True)).per_share[0])
    mid = float(dcf.value(p, 0.1, date, bridge, 1, dcf.Mistakes(terminal_discounted_mid_year=True)).per_share[0])
    assert no_cash == pytest.approx(ok - 6)
    assert mid > ok


def test_stub_year_counts_only_the_remaining_fraction():
    frac, mid, _ = dcf.timing(np.array([2025, 2026]), dt.date(2025, 7, 2))
    assert frac[0] == pytest.approx(0.5, abs=0.01) and frac[1] == 1
    assert mid[0] == pytest.approx(0.25, abs=0.01) and mid[1] == pytest.approx(0.5 + 0.5, abs=0.01)


def test_rim_equals_book_value_when_returns_equal_cost_of_equity():
    p = project(one_segment())
    ke, bv = 0.10, 37.5  # NOPAT 3.75 = 10% x 37.5, all paid out
    r = rim.value(p, ke, dt.date(2025, 1, 1), book_value=bv, net_debt=0, cost_of_debt=0.05, tax_rate=0.25, shares=1)
    assert float(r.equity[0]) == pytest.approx(bv, rel=1e-6)


def test_wacc():
    w = Wacc(
        rf=0.04,
        erp=0.05,
        crp=0.01,
        crp_exposure=1,
        beta_unlevered=1.0,
        debt_to_equity=0.25,
        tax_rate=0.2,
        cost_of_debt_pretax=0.06,
    )
    assert w.beta_levered == pytest.approx(1.2)
    assert w.cost_of_equity == pytest.approx(0.04 + 0.06 + 0.01)
    assert w.value == pytest.approx(0.8 * 0.11 + 0.2 * 0.048)
    assert blended_beta({"a": 1.2, "b": 0.8}, {"a": 3, "b": 1}) == pytest.approx(1.1)


def test_mean_reverting_paths_are_unbiased_and_positive():
    deck = {"li": np.full(30, 15_000.0)}
    paths = montecarlo.mean_reverting_paths(deck, {"li": 0.6}, phi=0.7, n=40_000, seed=1)["li"]
    assert paths.min() > 0
    assert paths.mean(axis=0)[-1] == pytest.approx(15_000, rel=0.03)
    assert np.median(paths[:, -1]) < 15_000  # right-skewed
