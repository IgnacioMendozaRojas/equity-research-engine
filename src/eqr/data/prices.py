"""Daily closing prices for the monitor.

Alpha Vantage (free key) serves daily closes for NYSE listings such as the SQM ADR.
The key is read from ALPHAVANTAGE_API_KEY and never written anywhere. Closes are
appended to the company's data/prices_daily.csv so the history stays in the repo.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import requests

URL = "https://www.alphavantage.co/query"
HEADER = "# Daily closes (USD) used by `eqr monitor`. Source column names the provider.\n"


class PriceError(Exception):
    pass


def alphavantage_daily(symbol: str, api_key: str | None = None, session=None) -> pd.DataFrame:
    """Last ~100 daily closes as a DataFrame with columns date, close."""
    key = api_key or os.getenv("ALPHAVANTAGE_API_KEY")
    if not key:
        raise PriceError("ALPHAVANTAGE_API_KEY is not set")
    params = {"function": "TIME_SERIES_DAILY", "symbol": symbol, "outputsize": "compact", "apikey": key}
    r = (session or requests).get(URL, params=params, timeout=30)
    r.raise_for_status()
    payload = r.json()
    series = payload.get("Time Series (Daily)")
    if not series:
        # the API answers 200 with a note when the key is wrong or the daily limit is reached
        msg = payload.get("Note") or payload.get("Information") or payload.get("Error Message") or "no data"
        raise PriceError(f"Alpha Vantage: {msg}")
    rows = [{"date": d, "close": float(v["4. close"])} for d, v in series.items()]
    return pd.DataFrame(rows).sort_values("date", ignore_index=True)


def read_log(path: Path) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame(columns=["date", "close", "source"])
    return pd.read_csv(path, comment="#", dtype={"date": str})


def append(path: Path, closes: pd.DataFrame, source: str) -> int:
    """Add closes not yet in the log; returns how many rows were added."""
    log = read_log(path)
    new = closes[~closes["date"].isin(set(log["date"]))].assign(source=source)
    if new.empty:
        return 0
    out = pd.concat([log, new], ignore_index=True).sort_values("date")
    Path(path).write_text(HEADER + out.to_csv(index=False), encoding="utf-8")
    return len(new)
