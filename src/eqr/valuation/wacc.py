"""Discount rate.

Cost of equity = rf + beta_L x ERP + lambda x CRP (Damodaran's country-risk
exposure form). No size premium and no ad-hoc "company-specific" premium: risks
that are specific to the company belong in the cash flows and the scenarios, not in
the rate, or they are counted twice.

The unlevered beta is a blend of business-line betas weighted by each line's share
of projected EBITDA, so a company whose value is moving towards lithium gets a
lithium-like beta.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Wacc:
    rf: float
    erp: float
    crp: float
    crp_exposure: float
    beta_unlevered: float
    debt_to_equity: float
    tax_rate: float
    cost_of_debt_pretax: float

    @property
    def beta_levered(self) -> float:
        return self.beta_unlevered * (1 + (1 - self.tax_rate) * self.debt_to_equity)

    @property
    def cost_of_equity(self) -> float:
        return self.rf + self.beta_levered * self.erp + self.crp_exposure * self.crp

    @property
    def weight_debt(self) -> float:
        return self.debt_to_equity / (1 + self.debt_to_equity)

    @property
    def value(self) -> float:
        wd = self.weight_debt
        return (1 - wd) * self.cost_of_equity + wd * self.cost_of_debt_pretax * (1 - self.tax_rate)

    def table(self) -> list[tuple[str, str]]:
        p = lambda x: f"{x:.2%}"  # noqa: E731
        return [
            ("Risk-free rate", p(self.rf)),
            ("Equity risk premium (mature market)", p(self.erp)),
            ("Country risk premium x exposure", f"{p(self.crp)} x {self.crp_exposure:.2f}"),
            ("Unlevered beta (EBITDA-weighted)", f"{self.beta_unlevered:.2f}"),
            ("Target debt / equity", p(self.debt_to_equity)),
            ("Levered beta", f"{self.beta_levered:.2f}"),
            ("Cost of equity", p(self.cost_of_equity)),
            ("Pre-tax cost of debt", p(self.cost_of_debt_pretax)),
            ("WACC", p(self.value)),
        ]


def blended_beta(betas: dict[str, float], weights: dict[str, float]) -> float:
    total = sum(max(weights.get(k, 0.0), 0.0) for k in betas)
    if total <= 0:
        raise ValueError("weights must be positive for at least one beta group")
    return sum(b * max(weights.get(k, 0.0), 0.0) for k, b in betas.items()) / total


def from_assumptions(d: dict, tax_rate: float, group_weights: dict[str, float]) -> Wacc:
    beta_u = blended_beta(d["beta_unlevered"], group_weights)
    return Wacc(
        rf=d["rf"],
        erp=d["erp"],
        crp=d.get("crp", 0.0),
        crp_exposure=d.get("crp_exposure", 1.0),
        beta_unlevered=beta_u,
        debt_to_equity=d["debt_to_equity"],
        tax_rate=tax_rate,
        cost_of_debt_pretax=d["rf"] + d["credit_spread"],
    )
