"""Minimal XBRL 2.1 instance reader.

Enough to pull primary financial statement facts out of a filing: contexts
(entity, period, dimensions), units and numeric facts. Used for the CMF's IFRS
filings (taxonomy CL-CI, an extension of the IFRS taxonomy, so concepts such as
`ifrs-full:Revenue` are the same ones the SEC API uses) and for any XBRL instance
on disk.

Not a validating processor: no linkbases, no calculation checks, no inline XBRL.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from xml.etree import ElementTree as ET

import pandas as pd

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"


def _q(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"


def _date(text: str | None) -> dt.date | None:
    return dt.date.fromisoformat(text.strip()[:10]) if text else None


def instance_from_zip(data: bytes) -> bytes:
    """The .xbrl instance inside a filing package (largest one if several)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.lower().endswith((".xbrl", ".xml")) and "_shell" not in n.lower()]
        instances = [n for n in names if n.lower().endswith(".xbrl")] or names
        if not instances:
            raise ValueError("no XBRL instance in the package")
        best = max(instances, key=lambda n: z.getinfo(n).file_size)
        return z.read(best)


def parse_instance(data: bytes) -> pd.DataFrame:
    """One row per numeric fact: concept, value, unit, decimals, start, end, instant, dimensions, members.

    `dimensions` is the number of axes on the fact's context (0 = consolidated, no breakdown);
    `members` holds them as a sorted tuple of (axis, member) QName pairs, e.g.
    (("cl-ci:TramosMorosidadEje", "cl-ci:AlDiaMiembro"),). Typed members carry their text value.
    """
    prefixes: dict[str, str] = {}
    for _event, item in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
        prefix, uri = item
        prefixes.setdefault(uri, prefix or "")
    root = ET.fromstring(data)

    contexts = {}
    for ctx in root.findall(_q(XBRLI, "context")):
        period = ctx.find(_q(XBRLI, "period"))
        dims = {
            m.get("dimension"): (m.text or "").strip()
            for m in ctx.iter()
            if m.tag in (_q(XBRLDI, "explicitMember"), _q(XBRLDI, "typedMember"))
        }
        contexts[ctx.get("id")] = {
            "start": _date(period.findtext(_q(XBRLI, "startDate"))),
            "end": _date(period.findtext(_q(XBRLI, "endDate"))),
            "instant": _date(period.findtext(_q(XBRLI, "instant"))),
            "dimensions": dims,
            "members": tuple(sorted(dims.items())),
        }

    units = {}
    for u in root.findall(_q(XBRLI, "unit")):
        measures = [m.text.split(":")[-1] for m in u.iter(_q(XBRLI, "measure")) if m.text]
        units[u.get("id")] = "/".join(measures)

    rows = []
    for el in root:
        ctx_id = el.get("contextRef")
        if ctx_id is None or el.get("unitRef") is None or ctx_id not in contexts:
            continue
        text = (el.text or "").strip()
        if not text:
            continue
        try:
            value = float(text)
        except ValueError:
            continue
        ns, local = el.tag[1:].split("}")
        c = contexts[ctx_id]
        rows.append(
            {
                "concept": f"{prefixes.get(ns, ns)}:{local}",
                "value": value,
                "unit": units.get(el.get("unitRef"), el.get("unitRef")),
                "decimals": el.get("decimals"),
                "start": c["start"],
                "end": c["end"] or c["instant"],
                "instant": c["instant"] is not None,
                "dimensions": len(c["dimensions"]),
                "members": c["members"],
            }
        )
    columns = ["concept", "value", "unit", "decimals", "start", "end", "instant", "dimensions", "members"]
    return pd.DataFrame(rows, columns=columns)


def period_values(facts: pd.DataFrame, period_end: dt.date, year_to_date: bool = True) -> pd.Series:
    """Consolidated, dimensionless values for one reporting date.

    Balance-sheet facts: instant at `period_end`. Flow facts: from 1 January (year to
    date, as Chilean filings report) or the 12 months ending at `period_end`.
    """
    f = facts[facts["dimensions"] == 0]
    inst = f[f["instant"] & (f["end"] == period_end)]
    start = dt.date(period_end.year, 1, 1) if year_to_date else period_end - dt.timedelta(days=364)
    flows = f[~f["instant"] & (f["end"] == period_end) & (f["start"] == start)]
    both = pd.concat([inst, flows])
    return both.groupby("concept")["value"].first()


def financials_from_instances(
    instances: dict[int, bytes],
    concept_map: dict[str, dict],
    month: int = 12,
    scale: float = 1e6,
) -> pd.DataFrame:
    """Concept x year table from {year: instance bytes}, using the SEC-style concept map."""
    out = {}
    for year, data in sorted(instances.items()):
        facts = parse_instance(data)
        end = (pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)).date()
        vals = period_values(facts, end)
        col = {}
        for name, spec in concept_map.items():
            v = next((vals[t] for t in spec["tags"] if t in vals.index), float("nan"))
            col[name] = abs(v) if spec.get("abs") else v
        out[year] = pd.Series(col) / scale
    return pd.DataFrame(out)
