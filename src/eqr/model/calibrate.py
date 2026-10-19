"""Turn reported history into the unit economics the projection uses.

Companies rarely publish segment costs. SQM publishes each segment's approximate
share of consolidated gross profit, which with revenue gives segment gross profit
and cost of sales. Depreciation is then allocated to segments by cost of sales, so
the cash (pre-depreciation) margin can be compared with the projection's
cash-margin assumptions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.store import Company


def segment_history(company: Company) -> pd.DataFrame:
    seg = company.segments.copy()
    fin = company.financials
    seg["price"] = seg["revenue"] / seg["volume"] * 1_000  # US$ m / kt -> US$/t
    gp = fin.loc["GrossProfit"]
    da = fin.loc["DepreciationAndAmortisation"]
    seg["gross_profit"] = seg["gross_profit_share"] * seg["year"].map(gp)
    seg["cost_of_sales"] = seg["revenue"] - seg["gross_profit"]
    cogs_total = seg.groupby("year")["cost_of_sales"].transform("sum")
    seg["depreciation"] = seg["cost_of_sales"] / cogs_total * seg["year"].map(da)
    seg["cash_cost"] = seg["cost_of_sales"] - seg["depreciation"]
    seg["cash_margin"] = 1 - seg["cash_cost"] / seg["revenue"]
    seg["cash_cost_per_t"] = seg["cash_cost"] / seg["volume"] * 1_000
    return seg


def price_volatility(company: Company, segment: str, until: int | None = None) -> float:
    """Annual volatility of log realised price changes (sample std)."""
    s = segment_history(company)
    s = s[(s["segment"] == segment) & s["price"].notna()]
    if until is not None:
        s = s[s["year"] <= until]
    lp = np.log(s.sort_values("year")["price"].to_numpy())
    return float(np.std(np.diff(lp), ddof=1))


def working_capital_ratios(company: Company, years: list[int]) -> dict[str, float]:
    """Receivables / revenue, inventories and payables / cash cost of sales, averaged."""
    f = company.financials
    cash_cost = f.loc["CostOfSales", years] - f.loc["DepreciationAndAmortisation", years]
    return {
        "receivables_pct_revenue": float(
            (f.loc["TradeAndOtherCurrentReceivables", years] / f.loc["Revenue", years]).mean()
        ),
        "inventory_pct_cost": float((f.loc["Inventories", years] / cash_cost).mean()),
        "payables_pct_cost": float((f.loc["TradeAndOtherCurrentPayables", years] / cash_cost).mean()),
    }


def ebitda(company: Company) -> pd.Series:
    """Gross profit - admin + D&A. A proxy: other operating income/expense excluded."""
    f = company.financials
    return f.loc["GrossProfit"] - f.loc["AdministrativeExpense"] + f.loc["DepreciationAndAmortisation"]


def net_debt(company: Company, year: int) -> float:
    f = company.financials
    debt = f.loc["OtherCurrentFinancialLiabilities", year] + f.loc["OtherNoncurrentFinancialLiabilities", year]
    cash = f.loc["CashAndCashEquivalents", year] + np.nan_to_num(f.loc["OtherCurrentFinancialAssets", year])
    return float(debt - cash)
