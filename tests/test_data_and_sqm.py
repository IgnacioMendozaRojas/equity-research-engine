import datetime as dt
import json
from pathlib import Path

import pytest

from eqr.data import cmf, news, sec
from eqr.data.store import load_company
from eqr.model import calibrate
from eqr.report.markdown import render
from eqr.valuation import backtest, engine

FIX = Path(__file__).parent / "fixtures"
SQM = Path(__file__).resolve().parents[1] / "companies" / "sqm"


def test_sec_annual_values_take_latest_filing_and_full_years_only():
    frame = sec.facts_frame(json.loads((FIX / "sec_concept.json").read_text()))
    values = sec.annual_values(frame)
    assert values.to_dict() == {2022: 110.0, 2023: 130.0}  # restated 2022 wins; amendment, H2 and 6-K ignored
    assert sec.annual_values(frame, include_amendments=True)[2022] == 999.0


def test_sec_client_requires_contact():
    with pytest.raises(ValueError):
        sec.SecClient("no contact", session=object())


def test_cmf_parses_chilean_numbers():
    s = cmf.parse_series(json.loads((FIX / "cmf_dolar.json").read_text()), "dolar")
    assert s.loc["2020-10-16"] == 785.5
    assert s.loc["2020-10-15"] == 1012.3


def test_news_rss_and_tagging():
    items = news.parse_rss((FIX / "news.xml").read_text())
    assert len(items) == 3 and items[0].source == "Example Wire"
    taxonomy = {"state": ["Codelco", "Nova Andino"], "prices": ["lithium price"], "tax": ["SII", "tax"]}
    tagged = news.tag(items, taxonomy)
    assert tagged["categories"].tolist() == ["state", "prices", "tax"]
    recent = news._since(items, dt.date(2026, 1, 1))
    assert [i.title for i in recent][0].startswith("Lithium")


@pytest.fixture(scope="module")
def company():
    return load_company(SQM)


def test_sqm_data_is_internally_consistent(company):
    f = company.financials
    gp = f.loc["Revenue"] - f.loc["CostOfSales"]
    assert (gp - f.loc["GrossProfit"]).abs().max() < 0.2
    seg = company.segments.groupby("year")["revenue"].sum()
    assert (seg / f.loc["Revenue"] - 1).abs().max() < 0.01  # segments add up to reported revenue
    tax_check = f.loc["ProfitBeforeTax"] - f.loc["IncomeTax"] - f.loc["ProfitLoss"]
    assert tax_check.abs().max() < 0.2


def test_sqm_calibration(company):
    seg = calibrate.segment_history(company)
    li = seg[(seg.segment == "lithium") & (seg.year == 2024)].iloc[0]
    assert li["price"] == pytest.approx(10_938.5, abs=1)
    e = calibrate.ebitda(company)
    assert e[2023] == pytest.approx(3_180.1, abs=1)  # SQM reported adjusted EBITDA
    assert e[2025] == pytest.approx(1_579.6, abs=1)


@pytest.mark.parametrize("date", ["2020-10-16", "2026-10-16"])
def test_sqm_valuation_runs_and_is_consistent(company, date):
    v = engine.run(company, date, sims=500)
    assert v.rating in {"BUY", "HOLD", "SELL"}
    dcf_ps, rim_ps = float(v.dcf.per_share[0]), float(v.rim.per_share[0])
    assert abs(rim_ps / dcf_ps - 1) < 0.25  # same projection, same cost of equity
    assert v.dcf.terminal_share < 0.2  # explicit horizon to 2060
    m = v.mistakes.set_index("case")["vs_correct"]
    assert m["Cash left out of the equity bridge"] < -0.05
    assert m["Perpetuity on the finite lithium concession"] > 0
    assert 0 < v.simulation["summary"]["prob_above_price"] < 1


def test_backtest_walk_starts_at_the_model(company):
    v = engine.run(company, "2020-10-16", with_tables=False)
    walk = backtest.value_walk(company, "2020-10-16")
    assert walk["value_per_share"].iloc[0] == pytest.approx(float(v.dcf.per_share[0]))
    fa = backtest.forecast_vs_actual(company, "2020-10-16")
    assert fa.loc[2022, "lithium_price_actual"] > 50_000


def test_report_renders(company, tmp_path):
    v = engine.run(company, "2026-10-16", sims=300)
    out = render(v, tmp_path, 300)
    text = out.read_text()
    for section in [
        "Investment summary",
        "Business description",
        "Valuation",
        "Financial analysis",
        "Investment risks",
        "Environmental, social and governance",
        "Sources",
    ]:
        assert f"## {section}" in text
    assert "{" not in text.split("## Business")[0]  # every placeholder filled
    assert (tmp_path / "figures" / "montecarlo-2026-10-16-dark.png").exists()
