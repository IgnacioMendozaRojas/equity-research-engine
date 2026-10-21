"""Command line: value, report, fetch-sec, fetch-cmf, reconcile, news, fetch-price, monitor."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

import pandas as pd


def _value(args) -> int:
    from .data.store import load_company
    from .valuation import engine

    c = load_company(args.company)
    v = engine.run(c, args.date, sims=args.sims)
    print(
        f"{c.config['short_name']} {v.valuation_date}: {v.rating}  target US${v.target_usd:,.2f} "
        f"(DCF {float(v.dcf.per_share[0]):,.2f}, RIM {float(v.rim.per_share[0]):,.2f})  "
        f"price US${v.price_usd:,.2f}  upside {v.upside:+.1%}  WACC {v.wacc.value:.2%}"
    )
    if v.simulation:
        s = v.simulation["summary"]
        print(
            f"Monte Carlo: median {s['median']:,.2f}, P5-P95 {s['p5']:,.2f}-{s['p95']:,.2f}, "
            f"P(value > price) {s['prob_above_price']:.0%}"
        )
    return 0


def _report(args) -> int:
    from .data.store import load_company
    from .report.markdown import render
    from .valuation import engine

    c = load_company(args.company)
    out = Path(args.out or c.root / "reports")
    out.mkdir(parents=True, exist_ok=True)
    for date in args.date or sorted(c.assumptions):
        v = engine.run(c, date, sims=args.sims)
        retro = date != max(c.assumptions)
        path = render(v, out, args.sims, retrospective=retro)
        print(f"wrote {path}")
    return 0


def _fetch_sec(args) -> int:
    import yaml

    from .data.sec import SecClient, build_financials

    root = Path(args.company)
    cfg = yaml.safe_load((root / "company.yaml").read_text())
    ua = args.user_agent or os.environ.get("SEC_USER_AGENT")
    if not ua:
        print("set --user-agent or SEC_USER_AGENT to 'Your Name your@email'", file=sys.stderr)
        return 2
    client = SecClient(ua, cache_dir=root / "data" / ".sec-cache")
    table = build_financials(client, cfg["sec_cik"], cfg["sec_concepts"])
    out = root / "data" / "financials_sec.csv"
    table.round(3).to_csv(out, index_label="concept")
    print(f"wrote {out} ({table.shape[0]} concepts, {table.columns.min()}-{table.columns.max()})")
    return 0


def _years(spec: str) -> list[int]:
    lo, _, hi = spec.partition("-")
    return list(range(int(lo), int(hi or lo) + 1))


def _fetch_cmf(args) -> int:
    import yaml

    from .data.cmf import CmfFilings

    root = Path(args.company)
    cfg = yaml.safe_load((root / "company.yaml").read_text())
    rut = args.rut or cfg.get("cmf_rut")
    if not rut:
        print("set --rut or cmf_rut in company.yaml (RUT without check digit, e.g. 93007000)", file=sys.stderr)
        return 2
    concepts = cfg.get("cmf_concepts") or cfg["sec_concepts"]
    filings = CmfFilings(root / "data" / ".cmf-cache", offline=args.offline)
    table = filings.financials(rut, _years(args.years), concepts, month=args.month)
    out = root / "data" / "financials_cmf.csv"
    table.round(3).to_csv(out, index_label="concept")
    print(f"wrote {out} ({table.shape[1]} periods)")
    return 0


def _reconcile(args) -> int:
    """Compare two financials files concept by concept (e.g. CMF vs SEC for a dual-listed issuer)."""
    root = Path(args.company) / "data"
    a = pd.read_csv(root / args.left, comment="#", index_col="concept")
    b = pd.read_csv(root / args.right, comment="#", index_col="concept")
    years = sorted(set(a.columns) & set(b.columns))
    concepts = sorted(set(a.index) & set(b.index))
    diff = (a.loc[concepts, years] - b.loc[concepts, years]).abs()
    rel = diff / b.loc[concepts, years].abs().where(lambda x: x > 0)
    flagged = rel.stack()[rel.stack() > args.tolerance]
    print(
        f"{len(concepts)} concepts x {len(years)} years compared; "
        f"{len(flagged)} differ by more than {args.tolerance:.1%}"
    )
    if len(flagged):
        print(flagged.rename("relative difference").to_string())
    return 1 if len(flagged) else 0


def _news(args) -> int:
    import yaml

    from .data.news import CsvNewsProvider, RssNewsProvider, tag

    root = Path(args.company)
    cfg = yaml.safe_load((root / "company.yaml").read_text())["news"]
    provider = CsvNewsProvider(Path(args.csv)) if args.csv else RssNewsProvider()
    since = dt.date.today() - dt.timedelta(days=args.days)
    items = provider.fetch(args.query or cfg["query"], since=since)
    df = tag(items, cfg["risk_keywords"])
    with pd.option_context("display.max_colwidth", 90, "display.width", 200):
        print(df.sort_values("published", ascending=False).head(args.limit).to_string(index=False))
    return 0


def _fetch_price(args) -> int:
    import yaml

    from .data import prices

    root = Path(args.company)
    cfg = yaml.safe_load((root / "company.yaml").read_text())
    symbol = args.symbol or cfg["tickers"]["nyse"]
    try:
        closes = prices.alphavantage_daily(symbol)
    except prices.PriceError as exc:
        print(f"::warning title=No price update::{exc}" if os.getenv("GITHUB_ACTIONS") else f"no price update: {exc}")
        return 0 if args.soft else 1
    added = prices.append(root / "data" / "prices_daily.csv", closes, f"Alpha Vantage {symbol}")
    print(f"{symbol}: {added} new closes, latest {closes['date'].iloc[-1]} at {closes['close'].iloc[-1]:,.2f}")
    return 0


def _monitor(args) -> int:
    import re

    from .data.store import load_company
    from .valuation import monitor

    c = load_company(args.company)
    data = monitor.latest(c)
    path = monitor.write(c, data)
    print(f"wrote {path}: {data['headline']}")
    readme = Path(args.readme)
    if readme.exists():
        tag = c.root.name
        text = readme.read_text(encoding="utf-8")
        block = _monitor_block(data)
        pattern = rf"(<!-- latest:{tag}:start -->\n)(?:.*?\n)?(<!-- latest:{tag}:end -->)"
        new = re.sub(pattern, lambda m: m.group(1) + block + "\n" + m.group(2), text, flags=re.S)
        if new != text:
            readme.write_text(new, encoding="utf-8")
    return 0


def _monitor_block(data: dict) -> str:
    def fmt(x: dict) -> str:
        v = x["value"]
        if x["unit"] == "share":
            return f"{v:+.1%}"
        if x["unit"] == "USD/t":
            return f"US${v:,.0f}/t"
        return f"US${v:,.2f}"

    rows = [f"| {x['label']} | {fmt(x)} | {x['period']} |" for x in data["metrics"]]
    return "\n".join(
        [
            f"**Monitor, {data['as_of']}.** {data['headline']}",
            "",
            "| Indicator | Value | As of |",
            "|---|---:|---|",
            *rows,
            "",
            f"*Updated automatically on {data['updated']}: the share price moves, the assumptions stay those of "
            f"the {data['assumptions_date']} report until it is revised.*",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eqr", description="Equity research engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("value", help="value a company at one date")
    v.add_argument("company")
    v.add_argument("date")
    v.add_argument("--sims", type=int, default=0)
    v.set_defaults(func=_value)

    r = sub.add_parser("report", help="write the Markdown report(s)")
    r.add_argument("company")
    r.add_argument("--date", action="append")
    r.add_argument("--sims", type=int, default=10_000)
    r.add_argument("--out")
    r.set_defaults(func=_report)

    f = sub.add_parser("fetch-sec", help="rebuild financials from SEC EDGAR XBRL")
    f.add_argument("company")
    f.add_argument("--user-agent")
    f.set_defaults(func=_fetch_sec)

    c = sub.add_parser("fetch-cmf", help="rebuild financials from CMF XBRL filings (Chilean issuers)")
    c.add_argument("company")
    c.add_argument("--rut", help="RUT without check digit; defaults to cmf_rut in company.yaml")
    c.add_argument("--years", default="2018-2025", help="e.g. 2018-2025 or 2024")
    c.add_argument("--month", type=int, default=12, help="12 for annual; 3, 6 or 9 for interim (year to date)")
    c.add_argument("--offline", action="store_true", help="only use packages already in data/.cmf-cache")
    c.set_defaults(func=_fetch_cmf)

    k = sub.add_parser("reconcile", help="compare two financials files in a company's data folder")
    k.add_argument("company")
    k.add_argument("--left", default="financials_cmf.csv")
    k.add_argument("--right", default="financials.csv")
    k.add_argument("--tolerance", type=float, default=0.005)
    k.set_defaults(func=_reconcile)

    n = sub.add_parser("news", help="latest headlines tagged by risk category")
    n.add_argument("company")
    n.add_argument("--query")
    n.add_argument("--csv", help="licensed terminal export (Factiva, Bloomberg) instead of RSS")
    n.add_argument("--days", type=int, default=30)
    n.add_argument("--limit", type=int, default=25)
    n.set_defaults(func=_news)

    fp = sub.add_parser("fetch-price", help="append the latest daily closes (Alpha Vantage, ALPHAVANTAGE_API_KEY)")
    fp.add_argument("company")
    fp.add_argument("--symbol", help="defaults to the NYSE ticker in company.yaml")
    fp.add_argument("--soft", action="store_true", help="exit 0 when no price can be fetched (scheduled runs)")
    fp.set_defaults(func=_fetch_price)

    m = sub.add_parser("monitor", help="latest.json: upside and implied commodity price at the latest close")
    m.add_argument("company")
    m.add_argument("--readme", default="README.md", help="README with <!-- latest:<company>:start/end --> markers")
    m.set_defaults(func=_monitor)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
