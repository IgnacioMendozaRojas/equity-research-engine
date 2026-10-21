"""Keep the latest valuation honest against the market between full reports.

The assumptions of the latest report stay fixed (they are analyst judgement and are
reviewed by hand). What moves is the share price: at each new close the monitor
recomputes the upside and the long-run price of the key commodity that would make
the model's value equal to the market price. The result is written to
<company>/latest.json, in the format shared by the other monitor repositories.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from ..data.prices import read_log
from ..data.store import Company
from . import engine


def latest(company: Company, prices_path: Path | None = None, updated: dt.date | None = None) -> dict:
    vdate = max(company.assumptions)
    a = company.assumptions[vdate]
    v = engine.run(company, vdate, with_tables=False)

    log = read_log(prices_path or company.root / "data" / "prices_daily.csv")
    if len(log):
        price, price_date = float(log["close"].iloc[-1]), str(log["date"].iloc[-1])
        previous = float(log["close"].iloc[-6]) if len(log) >= 6 else None  # about a week earlier
    else:
        price, price_date, previous = v.price_usd, str(v.valuation_date), None

    key = a["sensitivity_segment"]
    deck = a["segments"][key]["price"]
    deck_lr = float(deck[max(deck, key=int)])
    implied = engine.implied_long_run_price(company, vdate, target_usd=price)
    upside = v.target_usd / price - 1
    rating = engine.rate_bands(upside, a.get("rating_bands", {}))
    name = company.config["short_name"]
    ticker = company.config["tickers"]["nyse"]

    def metric(mid, label, value, unit, period, prev=None, change_type="relative"):
        change = None
        if prev is not None:
            change = value / prev - 1 if change_type == "relative" else value - prev
        return {
            "id": mid,
            "label": label,
            "value": round(value, 4),
            "unit": unit,
            "period": period,
            "previous": None if prev is None else round(prev, 4),
            "change": None if change is None else round(change, 4),
            "change_type": change_type,
        }

    return {
        "schema": 1,
        "id": f"{name.lower()}-implied-{key}-price",
        "repo": "equity-research-engine",
        "title": f"What {key} price is the market paying for in {name}?",
        "question": f"At today's share price, what long-run {key} price makes the model's value equal to the market?",
        "as_of": price_date,
        "frequency": "weekly",
        "updated": str(updated or dt.date.today()),
        "source": f"{ticker} daily close; model and assumptions of {vdate}",
        "headline": (
            f"At US${price:,.2f}, {name}'s share price implies {key} at about US${implied:,.0f}/t in the long run; "
            f"the model's deck uses US${deck_lr:,.0f}/t and gives US${v.target_usd:,.2f} per share ({rating})."
        ),
        "metrics": [
            metric("share_price", f"{ticker} share price", price, "USD", price_date, previous),
            metric(
                f"implied_long_run_{key}",
                f"Long-run {key} price implied by the share price",
                implied,
                "USD/t",
                price_date,
            ),
            metric(f"deck_long_run_{key}", f"Long-run {key} price in the model's deck", deck_lr, "USD/t", vdate),
            metric("target_price", "Model value per share (DCF + residual income)", v.target_usd, "USD", vdate),
            metric("upside", "Upside to model value", upside, "share", price_date, change_type="points"),
        ],
        "rating": rating,
        "assumptions_date": vdate,
        "figure": f"companies/{company.root.name}/reports/figures/montecarlo-{vdate}-light.png",
    }


def write(company: Company, data: dict) -> Path:
    out = company.root / "latest.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
