"""CMF (Comisión para el Mercado Financiero, Chile) API client.

The public CMF API (api.cmfchile.cl, free key on registration) serves market
indicators: USD/CLP observed rate, UF, EUR, UTM, IPC and bank interest rates. It
does not serve listed issuers' financial statements; those are published as
XBRL/PDF on the CMF website and need a separate downloader (see the roadmap in the
README).

Numbers come in Chilean format ("785,50"; "37.156,85").
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

BASE_URL = "https://api.cmfchile.cl/api-sbifv3/recursos_api"
RESOURCES = {"dolar": "Dolares", "euro": "Euros", "uf": "UFs", "utm": "UTMs", "ipc": "IPCs"}


def parse_cl_number(text: str) -> float:
    return float(text.replace(".", "").replace(",", "."))


@dataclass
class CmfClient:
    api_key: str
    session: object | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.session is None:
            import requests

            self.session = requests.Session()

    def _url(self, resource: str, path: str) -> str:
        return f"{BASE_URL}/{resource}/{path}?apikey={self.api_key}&formato=json"

    def series(self, resource: str, start: dt.date, end: dt.date) -> pd.Series:
        """Daily (or monthly) values between two dates, inclusive."""
        if resource not in RESOURCES:
            raise ValueError(f"unknown resource {resource!r}; choose from {sorted(RESOURCES)}")
        path = (
            f"periodo/{start.year}/{start.month:02d}/dias_i/{start.day:02d}/"
            f"{end.year}/{end.month:02d}/dias_f/{end.day:02d}"
        )
        resp = self.session.get(self._url(resource, path), timeout=30)
        resp.raise_for_status()
        return parse_series(resp.json(), resource)

    def on(self, resource: str, date: dt.date) -> float:
        path = f"{date.year}/{date.month:02d}/dias/{date.day:02d}"
        resp = self.session.get(self._url(resource, path), timeout=30)
        resp.raise_for_status()
        s = parse_series(resp.json(), resource)
        if s.empty:
            raise LookupError(f"no {resource} value published for {date}")
        return float(s.iloc[-1])


def parse_series(payload: dict, resource: str) -> pd.Series:
    rows = payload.get(RESOURCES[resource], [])
    s = pd.Series(
        [parse_cl_number(r["Valor"]) for r in rows],
        index=pd.to_datetime([r["Fecha"] for r in rows]),
        name=resource,
        dtype=float,
    )
    return s.sort_index()
