"""CMF (Comisión para el Mercado Financiero, Chile) data.

Two sources:

* `CmfClient`: the public CMF API (api.cmfchile.cl, free key on registration) for
  market indicators: USD/CLP observed rate, UF, EUR, UTM, IPC. Numbers come in
  Chilean format ("785,50"; "37.156,85").
* `CmfFilings`: issuers' IFRS financial statements, which the API does not serve.
  The CMF website publishes each quarterly filing as an XBRL package (taxonomy
  CL-CI, an IFRS extension). Packages are downloaded from the issuer's "Información
  financiera" page, cached, and parsed with `eqr.data.xbrl`.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import xbrl

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


# ---------------------------------------------------------------------------
# Issuer filings (XBRL)
# ---------------------------------------------------------------------------

SITE = "https://www.cmfchile.cl"
ENTITY_PAGE = SITE + "/institucional/mercados/entidad.php"
FILE_URL = SITE + "/institucional/inc/inf_financiera/ifrs/safec_ifrs_verarchivo.php"
_LINK = re.compile(r"""href=["']([^"']*safec_ifrs_verarchivo\.php[^"']*)["']""", re.IGNORECASE)


def xbrl_links(page_html: str) -> list[str]:
    """Absolute URLs of the XBRL packages linked from an issuer's financial-information page."""
    out = []
    for raw in _LINK.findall(page_html):
        url = urllib.parse.urljoin(SITE + "/institucional/mercados/", html.unescape(raw))
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        kind = (query.get("tipo_archivo", [""])[0] + query.get("desc_archivo", [""])[0]).upper()
        archivo = query.get("archivo", [""])[0].lower()
        if "XBRL" in kind or archivo.endswith((".zip", ".xbrl")):
            out.append(url)
    return list(dict.fromkeys(out))


def direct_url(rut: int | str, year: int, month: int, consolidated: bool = True) -> str:
    """Plain-parameter download URL. Works for filings stored as <rut>_<yyyymm>_<C|I>.zip;
    newer filings may carry a timestamp in the name, so prefer `xbrl_links` on the page."""
    kind = "C" if consolidated else "I"
    name = f"{rut}_{year}{month:02d}_{kind}.zip"
    params = {
        "rut": str(rut),
        "mm": f"{month:02d}",
        "aa": str(year),
        "archivo": name,
        "desc_archivo": "Estados financieros (XBRL)",
        "tipo_archivo": "XBRL",
    }
    return FILE_URL + "?" + urllib.parse.urlencode(params)


@dataclass
class CmfFilings:
    """Download and parse an issuer's IFRS XBRL filings.

    `cache_dir` keeps every package as <rut>_<yyyymm>.zip; with `offline=True` only the
    cache is read, so packages saved by hand from the CMF website work too.
    """

    cache_dir: Path
    session: object | None = field(default=None, repr=False)
    offline: bool = False
    entity_params: dict = field(
        default_factory=lambda: {
            "mercado": "V",
            "tipoentidad": "RVEMI",
            "vig": "VI",
            "control": "svs",
            "pestania": "3",
        }
    )

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.session is None and not self.offline:
            import requests

            self.session = requests.Session()
            self.session.headers["User-Agent"] = "Mozilla/5.0 (eqr research; contact in repository)"

    def _cached(self, rut, year, month) -> Path:
        return self.cache_dir / f"{rut}_{year}{month:02d}.zip"

    def filing_page(self, rut: int | str, year: int, month: int) -> str:
        params = {**self.entity_params, "rut": str(rut), "aa": str(year), "mm": f"{month:02d}"}
        resp = self.session.get(ENTITY_PAGE, params=params, timeout=60)
        resp.raise_for_status()
        resp.encoding = resp.encoding or "latin-1"
        return resp.text

    def package(self, rut: int | str, year: int, month: int = 12) -> bytes:
        path = self._cached(rut, year, month)
        if path.exists():
            return path.read_bytes()
        if self.offline:
            raise FileNotFoundError(f"{path} not in cache (offline mode)")
        tag = f"{year}{month:02d}"
        try:
            links = xbrl_links(self.filing_page(rut, year, month))
        except Exception as err:  # page layout or parameters changed: fall back to the direct URL
            print(f"filing page for {rut} {tag} unavailable ({err}); trying the direct URL")
            links = []
        # plain links name the period; tokenised (auth/send) links do not, so keep them all
        candidates = [u for u in links if tag in u] or links
        candidates.append(direct_url(rut, year, month))
        for url in candidates:
            resp = self.session.get(url, timeout=120)
            if resp.ok and resp.content[:2] == b"PK":
                path.write_bytes(resp.content)
                return resp.content
        raise LookupError(f"no XBRL package found for RUT {rut} {tag}")

    def financials(
        self, rut: int | str, years: list[int], concept_map: dict[str, dict], month: int = 12
    ) -> pd.DataFrame:
        instances = {}
        for y in years:
            try:
                instances[y] = xbrl.instance_from_zip(self.package(rut, y, month))
            except (LookupError, FileNotFoundError) as err:
                print(f"skip {y}: {err}")
        return xbrl.financials_from_instances(instances, concept_map, month=month)
