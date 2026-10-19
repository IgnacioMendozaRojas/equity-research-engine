"""Command line: `eqr value`, `eqr report`, `eqr fetch-sec`, `eqr news`."""

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

    n = sub.add_parser("news", help="latest headlines tagged by risk category")
    n.add_argument("company")
    n.add_argument("--query")
    n.add_argument("--csv", help="licensed terminal export (Factiva, Bloomberg) instead of RSS")
    n.add_argument("--days", type=int, default=30)
    n.add_argument("--limit", type=int, default=25)
    n.set_defaults(func=_news)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
