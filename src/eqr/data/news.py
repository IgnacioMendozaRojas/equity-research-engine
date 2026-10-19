"""News feed with pluggable providers.

Providers return `NewsItem`s. Two are included:

* `RssNewsProvider`  any RSS 2.0 feed; defaults to the public Google News search feed.
* `CsvNewsProvider`  headlines exported from a licensed terminal (Factiva, Bloomberg,
  Refinitiv). Licensed content stays on your machine: point the provider at your
  export and never commit it.

`tag` maps headlines to the risk categories used in the report, so the risk section
can show which risks are in the news.
"""

from __future__ import annotations

import datetime as dt
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol

import pandas as pd

GOOGLE_NEWS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


@dataclass(frozen=True)
class NewsItem:
    published: dt.datetime
    title: str
    source: str
    url: str = ""


class NewsProvider(Protocol):
    def fetch(self, query: str, since: dt.date | None = None) -> list[NewsItem]: ...


def parse_rss(xml_text: str) -> list[NewsItem]:
    root = ET.fromstring(xml_text)
    items = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        pub = node.findtext("pubDate")
        source = node.findtext("source") or ""
        published = parsedate_to_datetime(pub) if pub else dt.datetime.min
        items.append(NewsItem(published, title, source.strip(), (node.findtext("link") or "").strip()))
    return items


@dataclass
class RssNewsProvider:
    url_template: str = GOOGLE_NEWS
    session: object | None = field(default=None, repr=False)

    def fetch(self, query: str, since: dt.date | None = None) -> list[NewsItem]:
        if self.session is None:
            import requests

            self.session = requests.Session()
        url = self.url_template.format(query=urllib.parse.quote(query))
        resp = self.session.get(url, timeout=30, headers={"User-Agent": "eqr/0.1"})
        resp.raise_for_status()
        return _since(parse_rss(resp.text), since)


@dataclass
class CsvNewsProvider:
    """Read a terminal export. Columns are mapped with `columns`."""

    path: Path
    columns: dict[str, str] = field(
        default_factory=lambda: {"published": "date", "title": "headline", "source": "source"}
    )

    def fetch(self, query: str, since: dt.date | None = None) -> list[NewsItem]:
        df = pd.read_csv(self.path)
        c = self.columns
        mask = df[c["title"]].str.contains(query, case=False, na=False) if query else True
        items = [
            NewsItem(pd.Timestamp(r[c["published"]]).to_pydatetime(), r[c["title"]], r.get(c["source"], ""))
            for _, r in df[mask].iterrows()
        ]
        return _since(items, since)


def _since(items: list[NewsItem], since: dt.date | None) -> list[NewsItem]:
    if since is None:
        return items
    return [i for i in items if i.published.date() >= since]


def tag(items: Iterable[NewsItem], taxonomy: dict[str, list[str]]) -> pd.DataFrame:
    """One row per headline with the risk categories whose keywords it mentions."""
    rows = []
    for item in items:
        text = item.title.lower()
        hits = [cat for cat, words in taxonomy.items() if any(w.lower() in text for w in words)]
        rows.append(
            {"published": item.published, "title": item.title, "source": item.source, "categories": ", ".join(hits)}
        )
    return pd.DataFrame(rows, columns=["published", "title", "source", "categories"])
