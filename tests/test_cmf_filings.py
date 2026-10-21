import datetime as dt
import io
import zipfile
from pathlib import Path

import pytest

from eqr.data import cmf, xbrl

FIX = Path(__file__).parent / "fixtures"
CONCEPTS = {
    "Revenue": {"tags": ["ifrs-full:Revenue"]},
    "CostOfSales": {"tags": ["ifrs-full:CostOfSales"], "abs": True},
    "CashAndCashEquivalents": {"tags": ["ifrs-full:CashAndCashEquivalents"]},
    "Missing": {"tags": ["ifrs-full:Goodwill"]},
}


def package(instance: bytes, name: str = "93007000_202412_C") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{name}/{name}_shell.xsd", "<xsd/>")
        z.writestr(f"{name}/{name}.xbrl", instance)
    return buf.getvalue()


def test_parse_instance_reads_contexts_units_and_dimensions():
    facts = xbrl.parse_instance((FIX / "cmf_instance.xbrl").read_bytes())
    assert set(facts["concept"]) == {"ifrs-full:Revenue", "ifrs-full:CostOfSales", "ifrs-full:CashAndCashEquivalents"}
    assert (facts["unit"] == "USD").all()
    assert facts["dimensions"].max() == 1
    dimensional = facts[facts["dimensions"] == 1]["members"].unique().tolist()
    assert dimensional == [(("ifrs-full:SegmentsAxis", "cl-ci:LithiumMember"),)]
    assert (facts.loc[facts["dimensions"] == 0, "members"] == ()).all()


def test_period_values_keep_consolidated_year_to_date_only():
    facts = xbrl.parse_instance((FIX / "cmf_instance.xbrl").read_bytes())
    v = xbrl.period_values(facts, dt.date(2024, 12, 31))
    assert v["ifrs-full:Revenue"] == 4_528_761_000  # not the quarter, segment or prior year
    assert v["ifrs-full:CashAndCashEquivalents"] == 1_377_851_000


def test_financials_from_instances_matches_sec_layout():
    table = xbrl.financials_from_instances({2024: (FIX / "cmf_instance.xbrl").read_bytes()}, CONCEPTS)
    assert table.loc["Revenue", 2024] == pytest.approx(4528.761)
    assert table.loc["CostOfSales", 2024] == pytest.approx(3201.654)  # sign normalised
    assert table.loc["Missing", 2024] != table.loc["Missing", 2024]  # NaN: concept not filed


def test_instance_from_zip_skips_shell_files():
    data = (FIX / "cmf_instance.xbrl").read_bytes()
    assert xbrl.instance_from_zip(package(data)) == data


def test_xbrl_links_keeps_xbrl_packages_and_drops_pdfs():
    links = cmf.xbrl_links((FIX / "cmf_filing_page.html").read_text())
    assert len(links) == 2
    assert all(u.startswith("https://www.cmfchile.cl/institucional/inc/inf_financiera/ifrs/") for u in links)
    assert any("auth=YWJj" in u for u in links) and any("93007000_202412_C.zip" in u for u in links)


def test_direct_url_pattern():
    url = cmf.direct_url(93007000, 2024, 12)
    assert "archivo=93007000_202412_C.zip" in url and "tipo_archivo=XBRL" in url and "mm=12" in url


class FakeResponse:
    def __init__(self, content: bytes = b"", text: str = "", ok: bool = True):
        self.content, self.text, self.ok, self.encoding = content, text, ok, "latin-1"

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("http error")


class FakeSession:
    """Serves the filing page, then a non-zip for the tokenised link and a zip for the plain one."""

    def __init__(self, zip_bytes: bytes):
        self.zip_bytes, self.calls = zip_bytes, []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        if url == cmf.ENTITY_PAGE:
            return FakeResponse(text=(FIX / "cmf_filing_page.html").read_text())
        if "auth=" in url:
            return FakeResponse(content=b"<html>session expired</html>")
        return FakeResponse(content=self.zip_bytes)


def test_filings_download_cache_and_offline(tmp_path):
    zipped = package((FIX / "cmf_instance.xbrl").read_bytes())
    session = FakeSession(zipped)
    filings = cmf.CmfFilings(tmp_path, session=session)
    table = filings.financials(93007000, [2024], CONCEPTS)
    assert table.loc["Revenue", 2024] == pytest.approx(4528.761)
    assert (tmp_path / "93007000_202412.zip").exists()

    offline = cmf.CmfFilings(tmp_path, offline=True)
    assert offline.package(93007000, 2024) == zipped  # served from cache, no network
    with pytest.raises(FileNotFoundError):
        offline.package(93007000, 2023)


def test_reconcile_flags_differences(tmp_path, capsys):
    from eqr.cli import main

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "financials.csv").write_text("concept,2024\nRevenue,4528.761\nCostOfSales,3201.654\n")
    (tmp_path / "data" / "financials_cmf.csv").write_text("concept,2024\nRevenue,4528.761\nCostOfSales,3301.654\n")
    assert main(["reconcile", str(tmp_path)]) == 1
    assert "CostOfSales" in capsys.readouterr().out
    (tmp_path / "data" / "financials_cmf.csv").write_text("concept,2024\nRevenue,4528.761\nCostOfSales,3201.654\n")
    assert main(["reconcile", str(tmp_path)]) == 0
