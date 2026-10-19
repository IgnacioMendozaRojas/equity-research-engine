"""SEC EDGAR XBRL client.

Uses the public, keyless endpoints at data.sec.gov:

    /api/xbrl/companyconcept/CIK##########/{taxonomy}/{tag}.json   one concept, all filings
    /api/xbrl/companyfacts/CIK##########.json                      every concept

The SEC asks for a descriptive User-Agent with a contact address and at most ten
requests per second. Responses are cached to disk so a re-run does not hit the API.

Annual values are taken from annual forms (10-K, 20-F, 40-F) with fiscal period FY.
When a period is reported in several filings, the most recent filing wins: restated
comparatives replace the originally reported figure, which is what a valuation
should use.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

BASE_URL = "https://data.sec.gov/api/xbrl"
ANNUAL_FORMS = ("10-K", "20-F", "40-F")


def _cik(cik: int | str) -> str:
    return f"CIK{int(cik):010d}"


@dataclass
class SecClient:
    user_agent: str
    cache_dir: Path | None = None
    pause: float = 0.15
    session: object | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if "@" not in self.user_agent:
            raise ValueError("SEC requires a User-Agent with a contact e-mail, e.g. 'Name name@mail.com'")
        if self.session is None:
            import requests

            self.session = requests.Session()
        if self.cache_dir is not None:
            self.cache_dir = Path(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get(self, url: str, cache_name: str) -> dict:
        cached = self.cache_dir / cache_name if self.cache_dir else None
        if cached is not None and cached.exists():
            return json.loads(cached.read_text())
        resp = self.session.get(url, headers={"User-Agent": self.user_agent}, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if cached is not None:
            cached.write_text(json.dumps(payload))
        time.sleep(self.pause)
        return payload

    def concept(self, cik: int | str, taxonomy: str, tag: str) -> dict:
        url = f"{BASE_URL}/companyconcept/{_cik(cik)}/{taxonomy}/{tag}.json"
        return self._get(url, f"{_cik(cik)}_{taxonomy}_{tag}.json")

    def company_facts(self, cik: int | str) -> dict:
        url = f"{BASE_URL}/companyfacts/{_cik(cik)}.json"
        return self._get(url, f"{_cik(cik)}_facts.json")


def facts_frame(payload: dict) -> pd.DataFrame:
    """Flatten a companyconcept payload (or one concept of companyfacts) into rows."""
    rows = []
    tag = payload.get("tag")
    for unit, facts in payload.get("units", {}).items():
        for f in facts:
            rows.append({"tag": tag, "unit": unit, **f})
    cols = ["tag", "unit", "start", "end", "val", "fy", "fp", "form", "filed", "accn", "frame"]
    frame = pd.DataFrame(rows, columns=cols)
    for c in ("start", "end", "filed"):
        frame[c] = pd.to_datetime(frame[c])
    return frame


def annual_values(
    frame: pd.DataFrame,
    forms: Iterable[str] = ANNUAL_FORMS,
    unit: str | None = None,
    include_amendments: bool = False,
) -> pd.Series:
    """One value per fiscal year end, from the latest annual filing that reports it.

    Duration facts must span roughly a year (330-400 days) so that quarterly or
    half-year comparatives sitting in an annual filing are ignored. Instant facts
    (balance sheet) have no start date and are kept as they are.
    """
    allowed = set(forms) | ({f"{f}/A" for f in forms} if include_amendments else set())
    df = frame[frame["form"].isin(allowed) & (frame["fp"] == "FY")]
    if unit is not None:
        df = df[df["unit"] == unit]
    span = (df["end"] - df["start"]).dt.days
    df = df[df["start"].isna() | span.between(330, 400)]
    if df.empty:
        return pd.Series(dtype=float)
    latest = df.sort_values(["end", "filed"]).groupby("end").tail(1)
    out = latest.set_index(latest["end"].dt.year)["val"].astype(float)
    out.index.name = "year"
    return out.sort_index()


def build_financials(
    client: SecClient,
    cik: int | str,
    concept_map: dict[str, dict],
    scale: float = 1e6,
) -> pd.DataFrame:
    """Concept x year table in `scale` units.

    concept_map entries look like
        Revenue: {tags: ["ifrs-full:Revenue"]}
        DepreciationAndAmortisation: {tags: ["ifrs-full:DepreciationAndAmortisationExpense"], abs: true}
    The first tag that returns data wins. `abs: true` removes sign conventions that
    differ between filings (some filers report expenses as negatives).
    """
    series = {}
    for name, spec in concept_map.items():
        values = pd.Series(dtype=float)
        for qualified in spec["tags"]:
            taxonomy, tag = qualified.split(":")
            try:
                payload = client.concept(cik, taxonomy, tag)
            except Exception:  # 404 when the filer never used the tag
                continue
            values = annual_values(facts_frame(payload), unit=spec.get("unit", "USD"))
            if not values.empty:
                break
        if spec.get("abs"):
            values = values.abs()
        series[name] = values / scale
    table = pd.DataFrame(series).T
    table.columns = table.columns.astype(int)
    return table.sort_index(axis=1)
