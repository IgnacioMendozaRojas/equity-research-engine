"""Equity research report in Markdown.

Section order follows the CFA Institute Research Challenge format, with the answer
first: rating, target and the three reasons on page one, then the evidence. Prose
comes from the company's narrative/ folder. Numbers are filled in from the model, so
text and tables cannot drift apart.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ..model import calibrate
from ..model.royalty import CORFO_LITHIUM_CARBONATE
from ..valuation import backtest, engine
from ..valuation.engine import Valuation
from . import figures


def _pic(name: str, alt: str, rel: str) -> str:
    return (
        "<picture>\n"
        f'  <source media="(prefers-color-scheme: dark)" srcset="{rel}/{name}-dark.png">\n'
        f'  <img alt="{alt}" src="{rel}/{name}-light.png">\n'
        "</picture>\n"
    )


def _table(df: pd.DataFrame, fmt: str = "{:,.0f}", index: bool = True) -> str:
    cols = list(df.columns)
    head = ["", *map(str, cols)] if index else list(map(str, cols))
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for idx, row in df.iterrows():
        cells = [
            fmt.format(v)
            if isinstance(v, (int, float, np.floating)) and not pd.isna(v)
            else ("" if pd.isna(v) else str(v))
            for v in row
        ]
        lines.append("| " + " | ".join(([str(idx)] if index else []) + cells) + " |")
    return "\n".join(lines) + "\n"


def _read(path: Path) -> str:
    return path.read_text().strip() + "\n" if path.exists() else ""


def numbers(v: Valuation) -> dict:
    a = v.assumptions
    key = a.get("sensitivity_segment")
    deck = a["segments"][key]["price"] if key else {}
    sim = v.simulation["summary"] if v.simulation else {}
    li = a["segments"].get("lithium", {}).get("regimes", [{}])
    return {
        "price": v.price_local,
        "tp_usd": v.target_usd,
        "tp_local": v.target_local,
        "upside": v.upside,
        "upside_abs": abs(v.upside),
        "above_below": "above" if v.upside < 0 else "below",
        "rating": v.rating,
        "dcf": float(v.dcf.per_share[0]),
        "rim": float(v.rim.per_share[0]),
        "deck_lr": float(deck[max(deck)]) if deck else float("nan"),
        "implied_lr": round(engine.implied_long_run_price(v.company, str(v.valuation_date)), -2)
        if key
        else float("nan"),
        "ev_bn": float(v.dcf.ev[0]) / 1000,
        "iodine_bn": float(v.dcf.by_segment.get("iodine", np.zeros(1))[0]) / 1000,
        "li_share_now": float(li[0].get("share", 1.0)),
        "sims": len(v.simulation["values"]) if v.simulation else 0,
        "prob_above": sim.get("prob_above_price", float("nan")),
        "p5": sim.get("p5", float("nan")),
        "p95": sim.get("p95", float("nan")),
    }


def key_data(v: Valuation) -> pd.DataFrame:
    a, b = v.assumptions, v.bridge
    cur = a.get("currency_local", "USD")
    mcap = v.price_usd * v.shares
    rows = [
        ("Rating", v.rating),
        (f"Target price ({cur})", f"{v.target_local:,.2f}" if cur == "USD" else f"{v.target_local:,.0f}"),
        (
            f"Share price ({cur}), {v.valuation_date:%d %b %Y}",
            f"{v.price_local:,.2f}" if cur == "USD" else f"{v.price_local:,.0f}",
        ),
        ("Upside / downside", f"{v.upside:+.1%}"),
        *([("Target price (US$)", f"{v.target_usd:,.2f}")] if cur != "USD" else []),
        ("Shares outstanding (m)", f"{v.shares:,.1f}"),
        ("Market capitalisation (US$ m)", f"{mcap:,.0f}"),
        (f"Net financial debt (US$ m, {b.as_of})", f"{b.net_debt:,.0f}"),
        ("Enterprise value at market (US$ m)", f"{mcap + b.net_debt + b.minority_interest:,.0f}"),
        ("Discount rate (WACC)", f"{v.wacc.value:.2%}"),
    ]
    return pd.DataFrame(rows, columns=["Item", "Value"]).set_index("Item")


def financial_history(company) -> pd.DataFrame:
    f = company.financials
    e = calibrate.ebitda(company)
    years = list(f.columns)
    nd = [
        calibrate.net_debt(company, y) if not pd.isna(f.loc["OtherNoncurrentFinancialLiabilities", y]) else np.nan
        for y in years
    ]
    eq = f.loc["Equity"] - f.loc["NoncontrollingInterests"].fillna(0)
    df = pd.DataFrame(
        {
            "Revenue": f.loc["Revenue"],
            "EBITDA": e,
            "EBITDA margin": e / f.loc["Revenue"],
            "Net income (owners)": f.loc["ProfitAttributableToOwners"],
            "ROE": f.loc["ProfitAttributableToOwners"] / eq.shift(1),
            "Capex": f.loc["PurchaseOfPPE"],
            "Net financial debt": pd.Series(nd, index=years),
            "Dividends paid": f.loc["DividendsPaid"],
        }
    ).T
    return df


def _fmt_mixed(df: pd.DataFrame, pct_rows: set[str]) -> pd.DataFrame:
    out = df.copy().astype(object)
    for r in df.index:
        out.loc[r] = [("" if pd.isna(x) else (f"{x:.0%}" if r in pct_rows else f"{x:,.0f}")) for x in df.loc[r]]
    return out


def projection_table(v: Valuation, years: int = 6) -> pd.DataFrame:
    p = v.projection
    sl = slice(0, years)
    weight = sum(s["weight"][0] * s["ebitda"][0] for s in p.segments.values())
    df = pd.DataFrame(
        {
            "Revenue (consolidated)": p.total("revenue")[0][sl],
            "EBITDA, 100% basis": p.total("ebitda")[0][sl],
            "EBITDA, SQM's economic share": weight[sl],
            "Capex": p.total("capex")[0][sl],
            "Free cash flow to SQM": p.total("fcf")[0][sl],
            "Lithium volume (kt)": p.segments["lithium"]["volume"][0][sl],
            "Lithium price (US$/t)": p.segments["lithium"]["price"][0][sl],
        },
        index=p.years[sl],
    ).T
    return df


def render(v: Valuation, out_dir: Path, sims: int, retrospective: bool = False) -> Path:
    c = v.company
    date = str(v.valuation_date)
    narr = c.root / "narrative"
    fig_dir = out_dir / "figures"
    rel = "figures"
    n = numbers(v)
    labels = c.config.get("segments", {})
    short = {k: lab.split(" (")[0] for k, lab in labels.items()}
    md: list[str] = []

    title = "Retrospective: the October 2020 valuation" if retrospective else "Equity research report"
    md.append(f"# {c.config['short_name']}: {title}\n")
    md.append(
        f"*{c.name} · NYSE: {c.config['tickers']['nyse']} · Santiago: {c.config['tickers']['santiago']} · "
        f"valuation date {v.valuation_date:%d %B %Y}*\n"
    )
    md.append("> Prepared with public information only, as a portfolio exercise. Not investment advice.\n")

    md.append("## Investment summary\n")
    md.append(_table(key_data(v)))
    summary = _read(narr / date / "summary.md")
    if summary:
        md.append("\n" + summary.format(**n))

    if not retrospective:
        md.append("\n## Business description\n")
        md.append(_read(narr / "business.md"))
        seg = calibrate.segment_history(c)
        last = int(seg["year"].max())
        s = seg[seg["year"] == last].set_index("segment")
        tbl = pd.DataFrame(
            {
                "Revenue (US$ m)": s["revenue"],
                "Share of revenue": s["revenue"] / s["revenue"].sum(),
                "Volume (kt)": s["volume"],
                "Share of gross profit": s["gross_profit_share"],
            }
        ).rename(index=short)
        md.append(f"\n**{last} by business line**\n\n")
        md.append(
            _table(
                tbl.apply(
                    lambda col: col.map(
                        lambda x: "" if pd.isna(x) else (f"{x:.0%}" if col.name.startswith("Share") else f"{x:,.1f}")
                    )
                ),
                fmt="{}",
            )
        )

        md.append("\n## Industry overview and competitive positioning\n")
        md.append(_read(narr / "industry.md"))
        hist = seg[seg["segment"] == "lithium"].set_index("year")["price"].dropna().to_dict()
        decks = {}
        for d, a in c.assumptions.items():
            pr = a["segments"]["lithium"]["price"]
            first = int(a["first_year"])
            yrs = range(first, first + 8)
            from ..model.projection import path as _path

            decks[a.get("label", d).split(" (")[0] + " deck"] = dict(
                zip(
                    yrs, _path(pr, np.array(list(yrs)), a["segments"]["lithium"].get("price_growth", 0.02)), strict=True
                )
            )
        figures.lithium_prices(hist, decks, fig_dir)
        md.append("\n" + _pic("lithium-price", "Lithium realised price and decks", rel))
        corfo = pd.DataFrame(
            [
                (
                    f"{lo:,.0f}"
                    + (
                        f" - {CORFO_LITHIUM_CARBONATE[i + 1][0]:,.0f}" if i + 1 < len(CORFO_LITHIUM_CARBONATE) else " +"
                    ),
                    f"{r:.1%}",
                )
                for i, (lo, r) in enumerate(CORFO_LITHIUM_CARBONATE)
            ],
            columns=["Lithium carbonate price (US$/t)", "Corfo lease rate on that slice"],
        )
        md.append(
            "\n**Corfo lease on lithium carbonate (2018 agreement, to 2030)**\n\n"
            + _table(corfo, fmt="{}", index=False)
        )

    md.append("\n## Valuation\n")
    md.append(
        f"Blended target: **{v.weights['dcf']:.0%} DCF (US${n['dcf']:,.2f}) + {v.weights['rim']:.0%} residual income "
        f"(US${n['rim']:,.2f}) = US${v.target_usd:,.2f} per share.** Both use the same projection and the same cost "
        "of equity. The projection is built by segment as volume × price, with the Corfo lease, levies, capex tied "
        f"to capacity, and the fiscal regime of each period. It runs explicitly to {int(v.projection.years[-1])}, "
        f"so the terminal value is only {v.dcf.terminal_share:.0%} of the enterprise value.\n\n"
    )
    seg_vals = {k: float(x[0]) for k, x in v.dcf.by_segment.items() if abs(float(x[0])) > 1}
    figures.value_by_segment(seg_vals, short, fig_dir, f"value-by-segment-{date}")
    md.append(_pic(f"value-by-segment-{date}", "Enterprise value by business line", rel))
    b = v.bridge
    bridge = pd.DataFrame(
        [
            ("Enterprise value (DCF)", float(v.dcf.ev[0])),
            ("+ Cash and equivalents", b.cash),
            ("+ Other current financial assets", b.other_financial_assets),
            ("- Financial debt", -b.debt),
            ("- Minority interests", -b.minority_interest),
            ("+/- Other (see assumptions)", b.other),
            ("= Equity value", float(v.dcf.equity[0])),
            ("Per share (US$)", float(v.dcf.per_share[0])),
        ],
        columns=["Bridge (US$ m)", "Value"],
    ).set_index("Bridge (US$ m)")
    md.append(f"\n**From enterprise to equity value** (balance sheet {b.as_of})\n\n" + _table(bridge, "{:,.1f}"))
    md.append(
        "\n**Discount rate**\n\n"
        + _table(pd.DataFrame(v.wacc.table(), columns=["Input", "Value"]).set_index("Input"), "{}")
    )
    md.append(
        "\nNo size premium and no company-specific premium: company risks are in the cash flows and the scenarios. "
        "The unlevered beta blends lithium and chemicals betas by each group's share of SQM's projected EBITDA.\n"
    )

    proj = projection_table(v)
    md.append("\n**Projection (US$ m unless stated)**\n\n" + _table(proj, "{:,.0f}"))
    md.append(
        "\n*100% basis* includes every operation in full, after lease payments while they apply. *SQM's economic "
        "share* applies each period's fiscal regime: where the state's take is set as a share of the margin, lease "
        "payments are part of that take, so the 100% figure can jump when a lease ends.\n"
    )

    for name, tab in v.sensitivity.items():
        if name == "rate_x_long_run_price":
            md.append(
                "\n**DCF value per share (US$): discount rate × long-run lithium price (US$/t)**\n\n"
                + _table(tab, "{:,.1f}")
            )
        else:
            md.append(
                "\n**DCF value per share (US$): discount rate × terminal growth of perpetual segments**\n\n"
                + _table(tab, "{:,.1f}")
            )
    if v.scenarios is not None and len(v.scenarios):
        sc = v.scenarios.set_index("scenario")[["description", "target_usd", "upside", "rating"]].copy()
        sc.loc["base"] = ["Assumptions as stated", v.target_usd, v.upside, v.rating]
        sc = sc.loc[["base", *[i for i in sc.index if i != "base"]]]
        sc["target_usd"] = sc["target_usd"].map(lambda x: f"{x:,.2f}")
        sc["upside"] = sc["upside"].map(lambda x: f"{x:+.0%}")
        md.append(
            "\n**Scenarios**\n\n"
            + _table(
                sc.rename(
                    columns={
                        "description": "Scenario",
                        "target_usd": "Target (US$)",
                        "upside": "Upside",
                        "rating": "Rating",
                    }
                ),
                "{}",
            )
        )
    if v.simulation:
        s = v.simulation
        figures.distribution(s["values"], v.price_usd, v.target_usd, fig_dir, f"montecarlo-{date}")
        md.append("\n" + _pic(f"montecarlo-{date}", "Monte Carlo distribution", rel))
        sig = ", ".join(f"{short.get(k, k)} {x:.0%}" for k, x in s["sigma"].items())
        md.append(
            f"\nPrices follow a mean-reverting lognormal process around the deck (persistence φ = {s['phi']}, "
            f"annual volatility from the realised price history: {sig}). Median US${s['summary']['median']:,.1f}, "
            f"5th-95th percentile US${s['summary']['p5']:,.1f} to US${s['summary']['p95']:,.1f}.\n"
        )
    if v.mistakes is not None:
        mk = v.mistakes.set_index("case")
        mk["value_per_share"] = mk["value_per_share"].map(lambda x: f"{x:,.2f}")
        mk["vs_correct"] = mk["vs_correct"].map(lambda x: f"{x:+.1%}")
        md.append(
            "\n**Model checks: what three common errors would do to this valuation**\n\n"
            + _table(mk.rename(columns={"value_per_share": "DCF per share (US$)", "vs_correct": "vs correct"}), "{}")
        )

    if retrospective:
        md.append(backtest_section(v, fig_dir, rel))
    else:
        md.append("\n## Financial analysis\n")
        hist = financial_history(c)
        md.append("**History (US$ m)**\n\n" + _table(_fmt_mixed(hist, {"EBITDA margin", "ROE"}), "{}"))
        md.append(
            "\nEBITDA here is gross profit − administrative expense + D&A, which matches SQM's reported adjusted "
            "EBITDA within rounding in 2023-2025. 2023 net income reflects the restatement in the 2024 20-F that "
            "moved most of the US$1.1bn specific mining tax charge into the years it relates to. The 2025 earnings "
            "release still shows it in 2024.\n"
        )

        md.append("\n## Investment risks\n")
        risks = (
            yaml.safe_load((narr / date / "risks.yaml").read_text()) if (narr / date / "risks.yaml").exists() else []
        )
        risks = sorted(risks, key=lambda r: -r["probability"] * r["impact"])
        rt = pd.DataFrame(
            [(r["id"], r["name"], r["probability"], r["impact"], r["probability"] * r["impact"]) for r in risks],
            columns=["ID", "Risk", "Probability (1-5)", "Impact (1-5)", "Score"],
        ).set_index("ID")
        md.append("Ranked by probability × impact.\n\n" + _table(rt, "{}"))
        for r in risks:
            md.append(f"\n**{r['id']} · {r['name']}.** {r['text']} *Mitigant:* {r['mitigant']}\n")

        md.append("\n## Environmental, social and governance\n")
        md.append(_read(narr / "esg.md"))

    md.append("\n## Sources\n")
    md.append(sources(c, v))
    out = out_dir / f"{date}.md"
    out.write_text("\n".join(md))
    return out


def backtest_section(v: Valuation, fig_dir: Path, rel: str) -> str:
    c = v.company
    date = str(v.valuation_date)
    md = ["\n## Backtest: forecast vs what happened\n"]
    fa = backtest.forecast_vs_actual(c, date)
    figures.forecast_vs_actual(
        list(fa.index),
        fa["lithium_price_fcst"] / 1000,
        fa["lithium_price_actual"] / 1000,
        fig_dir,
        "backtest-lithium-price",
        unit="US$ thousand per tonne",
    )
    md.append(_pic("backtest-lithium-price", "Lithium price forecast vs realised", rel))
    tbl = pd.DataFrame(
        {
            "Lithium volume, forecast (kt)": fa["lithium_volume_fcst"],
            "Lithium volume, reported (kt)": fa["lithium_volume_actual"],
            "Lithium price, forecast (US$/t)": fa["lithium_price_fcst"],
            "Lithium price, reported (US$/t)": fa["lithium_price_actual"],
            "Revenue, forecast": fa["revenue_fcst"],
            "Revenue, reported": fa["revenue_actual"],
            "EBITDA, forecast": fa["ebitda_fcst"],
            "EBITDA, reported": fa["ebitda_actual"],
            "Capex, forecast": fa["capex_fcst"],
            "Capex, reported": fa["capex_actual"],
        }
    ).T
    md.append("\n**Forecast vs reported (US$ m unless stated)**\n\n" + _table(tbl, "{:,.0f}"))
    regimes = {
        "lithium": [
            {"to": 2024, "type": "corporate"},
            {"from": 2025, "to": 2030, "type": "margin_share", "share": 0.40},
            {"from": 2031, "to": 2060, "type": "margin_share", "share": 0.15},
        ],
        "potassium": [
            {"to": 2030, "type": "corporate"},
            {"from": 2031, "to": 2060, "type": "margin_share", "share": 0.15},
        ],
    }
    walk = backtest.value_walk(c, date, regimes)
    short = [
        "Model\nOct 2020",
        "+ lithium\nprices",
        "+ all prices\nand volumes",
        "+ actual\ncapex",
        "+ Codelco\nagreement",
    ]
    steps = list(zip(short[: len(walk)], walk["value_per_share"], strict=True))
    figures.waterfall(
        steps,
        fig_dir,
        "backtest-value-walk",
        reference=("share price then", v.price_usd),
    )
    md.append("\n" + _pic("backtest-value-walk", "Value walk from the 2020 model to hindsight", rel))
    w = walk.copy()
    w["value_per_share"] = w["value_per_share"].map(lambda x: f"{x:,.2f}")
    w["change"] = w["change"].map(lambda x: "" if pd.isna(x) else f"{x:+,.2f}")
    md.append(
        "\n"
        + _table(w.set_index("step").rename(columns={"value_per_share": "US$ per share", "change": "Change"}), "{}")
    )
    prices = c.share_prices.set_index("month") if c.share_prices is not None else None
    if prices is not None:
        p0, p1 = prices.loc["2020-10", "adjusted"], prices["adjusted"].iloc[-1]
        peak = prices["adjusted"].idxmax()
        hind = walk["value_per_share"].iloc[-1]
        md.append(
            f"\nWith perfect knowledge of 2020-2025, the October 2020 value would have been US${hind:,.2f} per share, "
            f"{hind / v.price_usd - 1:+.0%} against the price then (US${v.price_usd:,.2f}). "
            "Shareholders actually earned "
            f"{p1 / p0 - 1:+.0%} including dividends (ADR dividend-adjusted price {p0:,.2f} in October 2020, peak "
            f"{prices.loc[peak, 'adjusted']:,.2f} in {peak}, {p1:,.2f} in {prices.index[-1]}). "
            "What actually happened "
            f"to 2025 explains about {(hind / v.price_usd - 1) / (p1 / p0 - 1):.0%} of that return. The rest is what "
            "the market now expects from lithium after 2026; the 2026 report puts a price on it.\n"
        )
    return "\n".join(md)


def sources(company, v: Valuation) -> str:
    lines = [
        "- Financial statements: SEC EDGAR XBRL API (Form 20-F, CIK "
        f"{company.config['sec_cik']}), 2015-2024; SQM 4Q2025 earnings release (Form 6-K) for 2025.",
        "- Segment revenue, volumes and gross-profit shares: SQM full-year earnings releases, Form 6-K, 2016-2025; "
        "1H2026 run-rate from the 2Q2026 release.",
        "- Corfo lease schedule: SQM Form 6-K of January 2018 describing the Corfo agreement.",
        "- Nova Andino terms: Codelco and SQM announcements of 31 May 2024 and December 2025.",
        "- Market data: see companies/sqm/data/market.csv and share_prices.csv for each value's source and date.",
        f"- Assumptions: companies/sqm/assumptions/{v.valuation_date}.yaml, each with its rationale.",
        f"- Generated by eqr on {dt.date.today():%d %b %Y}.",
    ]
    return "\n".join(lines) + "\n"
