import pandas as pd
import pytest

from eqr.data import prices
from eqr.data.store import load_company
from eqr.valuation import monitor


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload, self.params = payload, None

    def get(self, url, params=None, timeout=None):
        self.params = params
        return FakeResponse(self.payload)


def test_alphavantage_daily_parses_closes_and_reports_limits():
    payload = {"Time Series (Daily)": {"2026-10-20": {"4. close": "61.10"}, "2026-10-19": {"4. close": "60.50"}}}
    df = prices.alphavantage_daily("SQM", api_key="k", session=FakeSession(payload))
    assert list(df["date"]) == ["2026-10-19", "2026-10-20"] and df["close"].iloc[-1] == 61.10
    with pytest.raises(prices.PriceError, match="limit"):
        prices.alphavantage_daily("SQM", api_key="k", session=FakeSession({"Information": "daily limit reached"}))
    with pytest.raises(prices.PriceError, match="not set"):
        prices.alphavantage_daily("SQM", api_key="", session=FakeSession(payload))


def test_price_log_only_appends_new_dates(tmp_path):
    log = tmp_path / "prices_daily.csv"
    first = pd.DataFrame({"date": ["2026-10-19", "2026-10-20"], "close": [60.5, 61.1]})
    assert prices.append(log, first, "test") == 2
    second = pd.DataFrame({"date": ["2026-10-20", "2026-10-21"], "close": [61.1, 62.0]})
    assert prices.append(log, second, "test") == 1
    assert list(prices.read_log(log)["date"]) == ["2026-10-19", "2026-10-20", "2026-10-21"]


def test_monitor_implied_price_matches_the_report_and_the_deck(tmp_path):
    c = load_company("companies/sqm")
    log = tmp_path / "p.csv"
    prices.append(log, pd.DataFrame({"date": ["2026-10-16"], "close": [60.23]}), "test")
    m = {x["id"]: x for x in monitor.latest(c, log)["metrics"]}
    assert m["implied_long_run_lithium"]["value"] == pytest.approx(25_100, rel=0.01)  # as in the report
    # at a price equal to the model's value, the implied price is the deck itself
    prices.append(log, pd.DataFrame({"date": ["2026-10-17"], "close": [m["target_price"]["value"]]}), "test")
    m2 = {x["id"]: x for x in monitor.latest(c, log)["metrics"]}
    assert m2["implied_long_run_lithium"]["value"] == pytest.approx(15_000, rel=0.005)
    assert m2["upside"]["value"] == pytest.approx(0, abs=1e-6)
