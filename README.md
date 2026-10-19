# equity-research-engine

[![CI](https://github.com/IgnacioMendozaRojas/equity-research-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/IgnacioMendozaRojas/equity-research-engine/actions/workflows/ci.yml)

A reusable equity valuation engine. Public filings go in; a CFA-style research report comes out, with every number traceable to a source or a stated assumption.

The first case is **SQM** (Sociedad Química y Minera de Chile), valued twice:

- **[October 2026: full report](companies/sqm/reports/2026-10-16.md).** **SELL**, target **US$42.2** vs US$60.2 per ADR. The share price assumes lithium at about **US$25,100/t** from 2028; our deck uses US$15,000/t.
- **[October 2020: retrospective](companies/sqm/reports/2020-10-16.md).** The same engine, restricted to what was public on 16 October 2020, gives **HOLD** at US$34.9 vs US$34.6. It is then held against what actually happened.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="companies/sqm/reports/figures/backtest-value-walk-dark.png">
  <img alt="Value walk from the October 2020 model to hindsight" src="companies/sqm/reports/figures/backtest-value-walk-light.png">
</picture>

With perfect knowledge of 2020-2025, the 2020 value rises only from US$36.6 to US$43.6, while shareholders earned +89% including dividends. The 2022 lithium spike (US$52,000/t realised) mostly went to the Chilean state: the Corfo lease takes 40% of every dollar above US$10,000/t before income tax. The extra volume needed three to six times the capex. The Codelco agreement cuts SQM's share of the Atacama margin to about 15% from 2031. The rest of the return is the market's higher long-run lithium price.

## Why it is built this way

I won the CFA Institute Research Challenge South America regional final (2020-21) with SQM. This repository is a rebuild from scratch with public data. The competition report and model belong to CFA Institute and are not here. The design fixes the errors that are easy to make in a spreadsheet valuation of a resource company:

| Choice | Why |
|---|---|
| **Segments as volume × price**, each with its own cost, capex and fiscal regime | A company whose value is moving from fertilisers to lithium cannot be forecast with one growth rate |
| **Fiscal regimes by period**: corporate tax, or a share of the margin under a state agreement | Chilean lithium is a concession with a progressive lease (to 2030) and a state partner (2031-2060). Royalties and state take decide how much of a price spike the company keeps |
| **Finite assets end; no perpetuity on a concession** | A Gordon growth model on lithium assumes the 2060 concession lasts forever |
| **Explicit horizon to 2060** | Terminal value is 5-12% of EV, not 80% |
| **Capex tied to capacity additions** | Tripling capacity with capex equal to depreciation overstates free cash flow |
| **Working capital split by driver**: receivables on revenue, inventories and payables on cost | A price spike does not mean the company stocked up at the new price |
| **Equity bridge with cash and financial assets**, terminal value discounted from year end | Leaving cash out undervalues SQM by 11-23% (see the model-check table in each report) |
| **DCF and residual income from one projection and one cost of equity** | The two methods cross-check each other instead of averaging inconsistent answers |
| **No size or "company-specific" premium in the discount rate** | Company risks belong in the cash flows and the scenarios, or they are counted twice |
| **Monte Carlo on mean-reverting lognormal prices**, volatility from realised prices | Prices stay positive and skewed; the deck is the mean, not a point forecast |
| **Backtest built in** | Any past valuation can be re-run with hindsight, one assumption at a time |

## Quick start

```bash
pip install -e ".[dev]"

eqr value companies/sqm 2026-10-16 --sims 10000
# SQM 2026-10-16: SELL  target US$42.23 (DCF 41.30, RIM 44.40)  price US$60.23  upside -29.9%  WACC 10.18%
# Monte Carlo: median 35.36, P5-P95 16.45-85.67, P(value > price) 15%

eqr report companies/sqm                 # writes companies/sqm/reports/*.md and figures
SEC_USER_AGENT="Your Name you@mail.com" eqr fetch-sec companies/sqm   # rebuild financials from SEC XBRL
eqr fetch-cmf companies/sqm --years 2018-2025   # same from the CMF's IFRS XBRL filings (Chilean issuers)
eqr reconcile companies/sqm              # CMF vs SEC, concept by concept
eqr news companies/sqm --days 30         # headlines tagged by risk category
eqr news companies/sqm --csv my_factiva_export.csv   # same, from a licensed terminal export
```

## How it works

```
data/            providers             model/                 valuation/                 report/
SEC EDGAR XBRL ─┐
CMF XBRL filings┤                      calibrate: unit        wacc: CAPM + CRP, beta    markdown: CFA sections,
CMF API (FX/UF) ├─► company folder ──► economics from    ──► blended by EBITDA     ──► answer first, numbers
News (RSS/CSV) ─┘   data/*.csv         history               dcf: mid-year, bridge     filled from the model
                    assumptions/*.yaml projection: segments  rim: clean surplus        figures: light + dark
                    narrative/*.md     × regimes × years     montecarlo, scenarios,
                                       (n paths × T years)   sensitivity, backtest
```

The projection works on arrays of shape `(paths, years)`, so the base case, scenarios and 10,000 Monte Carlo paths all run through the same code. Monte Carlo is vectorised and takes under a second.

## Adding a company

```
companies/<name>/
  company.yaml               identifiers, segment names, SEC concept map, news keywords
  data/financials.csv        concept x year (eqr fetch-sec builds it for SEC filers)
  data/segments.csv          year, segment, revenue, volume, gross_profit_share
  data/market.csv            dated market inputs with their source
  assumptions/<date>.yaml    one file per valuation date; every number commented
  narrative/                 business, industry, ESG prose; <date>/summary.md, risks.yaml
```

Assumptions are plain YAML: a deck is a `{year: value}` map, extended at a growth rate; a regime is `{from, to, type, share, probability}`. Scenarios are partial overrides of the same file. For a company outside resources, use `cash_margin` segments without royalties or regimes.

## Data and licensing

- **SEC EDGAR XBRL** (free, no key): annual statements for any 10-K, 20-F or 40-F filer. The latest filing wins, so restated comparatives replace originally reported figures. That matters for SQM's 2023 numbers.
- **CMF Chile, issuers' statements**: every Chilean issuer files its IFRS statements quarterly as an XBRL package (taxonomy CL-CI, an IFRS extension) on cmfchile.cl. `eqr fetch-cmf` finds the package on the issuer's financial-information page, caches it, and reads the consolidated year-to-date facts with a small XBRL parser. It uses the same `ifrs-full` concepts as the SEC connector, so `eqr reconcile` can check one source against the other for dual-listed companies. Packages saved by hand into `data/.cmf-cache/` also work, with `--offline`.
- **CMF Chile API** (free key): USD/CLP, UF and other indicators.
- **News**: Google News RSS by default. Licensed sources (Factiva, Bloomberg, Refinitiv) plug in as local CSV exports. They are git-ignored, and licensed content is never committed.
- SQM inputs are listed with their source in `companies/sqm/data/*.csv` and the "Sources" section of each report.

## Validation: CMF vs SEC for SQM

SQM files the same IFRS statements with both regulators, so `eqr fetch-cmf` followed by `eqr reconcile` tests the CMF connector end to end. Run on 19 Oct 2026 for 2020-2024: 24 concepts × 5 years, 110 of 120 values agree within 0.5%. Nine of the ten differences are one event. The SEC series uses the FY2024 20-F, which restated 2023 for the US$1.1bn specific mining tax. The CMF filings are as originally filed, with the charge in 2024:

| Concept | Year | CMF vs SEC | Explanation |
|---|---|---|---|
| Income tax | 2023 | US$787m vs US$1,877m | charge moved into 2023 by the restatement |
| Income tax | 2024 | US$1,372m vs US$283m | charge booked in 2024 in the original filing |
| Net income, total and to owners | 2023, 2024 | differ by the charge | same |
| Equity, total assets | 2023 | +24%, +9% | restatement reduced equity and the tax receivable |
| Cash from operations | 2023 | 9% | reclassification in the restated cash flow |
| Total assets | 2021 | 1.9% | not yet explained |

## Roadmap

- Second company from CMF filings only (a Chilean issuer without SEC filings)
- Peer multiples from public filings, for a market-approach cross-check
- Scheduled refresh: a GitHub Action that pulls new filings and news and re-renders the reports
- Excel export of the projection for reviewers who live in spreadsheets

## Tests

```bash
pytest       # 36 tests: closed-form DCF, Corfo brackets, regimes, SEC and CMF XBRL parsing, SQM data checks, report rendering
ruff check .
```

---

Built from public information as a portfolio project. Not investment advice.
