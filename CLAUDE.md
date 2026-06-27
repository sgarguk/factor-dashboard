# CLAUDE.md — Factor Donchian Dashboard
## Lighthouse Canton Pte. Ltd. · Internal Research Tool

> This file gives Claude (and Claude Code) full context about this repository.
> Read it before making any changes to the codebase.

---

## What this project is

A live factor-rotation dashboard published at **sgarguk.github.io/factor-dashboard/**
that identifies the prevailing equity factor each day using a pairwise Donchian
channel methodology. It auto-updates every weekday via GitHub Actions at 22:00 UTC.

---

## Repository structure

```
factor-dashboard/
├── generate.py                   ← THE ONLY FILE YOU SHOULD EDIT
├── requirements.txt              ← Python dependencies
├── index.html                    ← 7-ETF dashboard  (GENERATED — do not hand-edit)
├── 5etf.html                     ← 5-ETF dashboard  (GENERATED — do not hand-edit)
├── CLAUDE.md                     ← this file
└── .github/
    └── workflows/
        └── update.yml            ← GitHub Actions cron (22:00 UTC Mon–Fri)
```

**Rule:** `index.html` and `5etf.html` are outputs of `generate.py`. Never edit them
directly — they will be overwritten on the next run.

---

## The two universes

| File | Tickers | Start date |
|------|---------|------------|
| `index.html` | SPMO · DGRO · SPYG · SPHQ · IVE · GLD · DBMF | Jul 2019 |
| `5etf.html` | SPMO · DGRO · SPYG · SPHQ · IVE | Jan 2016 |

The 7-ETF version includes GLD (Gold) and DBMF (Managed Futures) as defensive legs,
which significantly improves the Sharpe ratio and reduces max drawdown.

---

## Methodology — pairwise Donchian ratio with latching

### Core signal

For every pair of ETFs (A, B):

```
ratio     = price_A / price_B
dh        = rolling_max(ratio, N=30).shift(1)   # 1-day shift = no lookahead
dl        = rolling_min(ratio, N=30).shift(1)

if ratio > dh  →  A wins  (latch = +1, vote for A)
if ratio < dl  →  B wins  (latch = -1, vote for B)
else           →  IN BAND: carry last confirmed direction
```

The latch means an IN-BAND ratio still votes — it carries the last breakout
direction until the ratio breaks the opposite channel boundary.

### Vote tally

Each ETF counts its total wins across all pairs it participates in. Winner =
most votes. Tie-break = highest closing price (a simple, transparent rule).

- 5-ETF universe: C(5,2) = **10 pairs**, max 4 votes per ETF
- 7-ETF universe: C(7,2) = **21 pairs**, max 6 votes per ETF

### Backtest logic

```
position[d]  = winner on day d (from vote tally)
return[d+1]  = daily return of position[d]   ← standard next-day execution
```

No leverage. No transaction costs modelled (these are signals, not a managed fund).

### Key parameters

| Parameter | Value | Note |
|-----------|-------|------|
| N (lookback) | 30 | Donchian channel width |
| Shift | 1 day | Prevents lookahead bias |
| Confirmation | None | Immediate signal (no 2-day lag for ratio signals) |
| Tiebreak | Highest price | Simple, transparent |
| Execution | Next-day close | Realistic |

---

## Design rules (do not change without discussion)

### Visual identity
- **Navy:** `#1C2B3A` (--nv) — headers, card backgrounds
- **Dark navy:** `#243446` (--nv2) — card header bars
- **Crimson:** `#C0392B` (--rd) — accents, active holding border, Strategy line
- **Background:** `#F0F4F8` (--bg)
- **Border:** `#DDE3EA` (--bd)
- **Numbers/codes:** `'Courier New', monospace` — always for prices, metrics, tickers
- **Body text:** `'Segoe UI', system-ui, sans-serif`

This matches the existing Donchian dashboard at sgarguk.github.io/donchian-dashboard/

### Chart library
Chart.js 4.4.1 via cdnjs CDN. **Do not switch to Plotly or other libraries.**
All charts are rendered client-side — no server needed.

### Signal card (left panel)
Must show: Active holding ticker (large, colored), factor name, Days In, Since date,
Previous holding, Switch count, current prices for all tickers as badges.
This matches the design screenshot from the existing dashboard.

---

## How to extend

### Add a new ETF to the 7-ETF universe

1. Add it to `UNIVERSES[1]['tickers']` in `generate.py`
2. Add its metadata to `META` dict: `{'name': '...', 'color': '#...'}`
3. Add its badge colors to `BADGE` dict
4. If start date is after 2019-07-01, update `UNIVERSES[1]['start']`
5. Test locally: `python generate.py`

### Change Donchian parameters

At the top of `generate.py`:
```python
N, SHIFT = 30, 1    # change N for longer/shorter lookback
```

### Add a third universe (e.g., sector ETFs)

Copy the universe dict pattern in `UNIVERSES`, add a new `fname`, and add a nav
link in `build_html()` pointing to the new file.

---

## Running locally

```bash
pip install -r requirements.txt
python generate.py
# Opens index.html and 5etf.html in your browser
```

Data is fetched live from Yahoo Finance via yfinance. The script always pulls
up to the most recent available close.

---

## GitHub Actions schedule

```yaml
cron: '0 22 * * 1-5'    # 22:00 UTC, Mon–Fri
```

US markets close at ~21:00 UTC (summer/EDT). The 1-hour buffer ensures same-day
closing prices are available in Yahoo Finance before the script runs.

Manual trigger: GitHub → Actions → "Update Factor Dashboard" → "Run workflow".

---

## Owner / context

- **Owner:** Sunil Garg, Group CIO, Lighthouse Canton Pte. Ltd.
- **Purpose:** Daily factor regime identification for internal investment process
- **Audience:** Investment team (internal only — not for client distribution)
- **Related dashboard:** sgarguk.github.io/donchian-dashboard/ (SPY/QQQ/GLD/DBMF)
