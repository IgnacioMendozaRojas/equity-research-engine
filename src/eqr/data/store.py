"""Load a company folder: config, financial history, segment history, market data."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml


@dataclass
class Company:
    root: Path
    config: dict
    financials: pd.DataFrame  # concept x year, US$ m
    segments: pd.DataFrame  # year, segment, revenue, volume, gross_profit_share
    market: pd.DataFrame  # date, item, value, unit, source
    share_prices: pd.DataFrame | None = None
    assumptions: dict[str, dict] = field(default_factory=dict)  # valuation date -> assumptions

    @property
    def name(self) -> str:
        return self.config["name"]

    def market_value(self, item: str, on: str | dt.date | None = None) -> float:
        """Latest value of `item` on or before `on`."""
        rows = self.market[self.market["item"] == item]
        if on is not None:
            rows = rows[rows["date"] <= pd.Timestamp(on)]
        if rows.empty:
            raise KeyError(f"no market value for {item!r} on or before {on}")
        return float(rows.sort_values("date")["value"].iloc[-1])

    def history(self, until: int | None = None) -> pd.DataFrame:
        f = self.financials
        return f.loc[:, [c for c in f.columns if until is None or c <= until]]


def _csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, comment="#")


def load_company(root: str | Path) -> Company:
    root = Path(root)
    config = yaml.safe_load((root / "company.yaml").read_text())
    fin = _csv(root / "data" / "financials.csv").set_index("concept")
    fin.columns = fin.columns.astype(int)
    seg = _csv(root / "data" / "segments.csv")
    market = _csv(root / "data" / "market.csv")
    market["date"] = pd.to_datetime(market["date"])
    prices = None
    if (root / "data" / "share_prices.csv").exists():
        prices = _csv(root / "data" / "share_prices.csv")
    assumptions = {}
    for path in sorted((root / "assumptions").glob("*.yaml")):
        a = yaml.safe_load(path.read_text())
        assumptions[str(a["valuation_date"])] = a
    return Company(root, config, fin, seg, market, prices, assumptions)
