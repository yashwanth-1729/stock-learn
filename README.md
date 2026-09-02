# Indian Market Historical Analysis

A visual historical study of any Indian stock or index — how it actually behaved, one calendar year
at a time. Not a trading dashboard: no RSI, no MACD, no Bollinger bands. Just the real daily record.

Search **any of ~2,500 NSE-listed companies**, any BSE listing, or the major indices. Opens on the
NIFTY 50, whose series ships embedded and verified.

**NIFTY 50: 4,673 verified sessions · 17 September 2007 → 1 September 2026**
**Everything else: fetched live — Reliance and Infosys reach back to 1996**

## What's in it

- A **summary table** of every year: first and last trading day, starting and ending close, and two
  return figures — the first-day-to-last-day return, and the conventional calendar-year return
  measured from the previous year's final close.
- **A separate chart for every year**, never combined. Hover any point for the exact date, close,
  day-over-day change and that session's open/high/low. Drag, scroll or pinch to zoom.
- **Any two dates** — chart and measure any stretch of history, with return, CAGR, high/low,
  best and worst day, up/down day counts and max drawdown.
- **Annual returns compared** as a labelled bar chart.
- **A ₹10,000 price-return simulation** for each year, stated plainly as price-return only.
- **The biggest single days**, detected from the data, with documented drivers named where they
  are corroborated and left blank where they are not.

## Data, and why it is built this way

Daily open/high/low/close. For the NIFTY 50 the series is reconciled from two sources:

| Source | Role |
| --- | --- |
| [NSE official archives](https://nsearchives.nseindia.com/content/indices/) — `ind_close_all_<DDMMYYYY>.csv` | Authoritative end-of-day index file. Only published from 2013 onward. |
| Yahoo Finance `^NSEI` daily chart API | Bulk series. Its NIFTY history begins 17 September 2007. |

The bulk feed alone is **not** good enough. It is missing 24 genuine NSE sessions, including the
actual first trading day of **2016, 2018 and 2019** — so an unpatched build reports 2016 as starting
on 4 January at 7,791.30 instead of **1 January at 7,963.20**, giving three years the wrong annual
return. Every one of those sessions was recovered from NSE's own files.

Verification performed at build time:

- A stratified random sample of **195 trading days matched official NSE to the paisa on every OHLC
  value — 195/195**.
- Every weekday absent from the bulk feed was checked against NSE to prove it was a real holiday
  and not a silent drop.
- Each year's first and last trading day is confirmed against the exchange record.
- The encode/decode round-trip is asserted across all 4,673 rows.

The build refuses to emit data if any of these fail.

### Everything other than the NIFTY 50

Any other instrument is served live by `api/quote.js` from the bulk feed. That is the same feed
which matched NSE exactly on all 195 sampled index days, so it is not suspect — but it has **not**
been reconciled security by security against the exchange record. Treat single-stock figures as
good, not audited.

Nothing about any company is written into this repository:

- The **searchable universe** comes from NSE's own equity master file
  (`EQUITY_L.csv`, ~2,500 listed companies), fetched and cached at request time. Newly listed
  companies appear without anything here being edited.
- **Splits and dividends** are the instrument's own, reported by the feed as dated events and shown
  under Corporate actions.
- Prices are **split-adjusted**, so a 2:1 split renders as continuous history rather than a phantom
  50% crash.
- The **named market events** are whole-of-market days — budgets, elections, the COVID crash — which
  moved every Indian listing, so they apply whichever instrument is loaded.
- The **"biggest single days" threshold adapts** to each instrument's own typical daily move: about
  2.5% for the index, 4.5% for Reliance.
- **History length follows the listing.** A company that listed in 2022 starts in 2022 and the
  default window follows it, rather than showing empty years.

### Known limits, stated rather than papered over

- **History starts in September 2007.** No reachable source publishes reliable daily NIFTY closes
  before then — NSE's archive does not go back that far and the index provider's bulk endpoint is
  closed. The record begins where the real data begins.
- **Granularity is one row per session.** Intraday history is not available over a span this long,
  so date pickers work in whole days.
- **A few Saturdays and Sundays appear.** These are real, officially settled NSE sessions — Diwali
  Muhurat trading and Union Budget weekend sittings — kept so the data matches the exchange calendar.
- **Sessions before 2013 rest on the bulk feed alone**, since NSE's archive files do not exist for them.
- Charts plot **price**, which excludes dividends and so understates an investor's actual return.
  Declared dividends are listed separately under Corporate actions.
- A **delisted or renamed symbol** will not resolve. Search by company name to find its current
  ticker.
- Nothing here is investment advice. It is a record of what already happened.

## Layout

```
index.html      the whole study tool; ships with the NIFTY 50 series embedded
api/quote.js    price history for any instrument (the upstream feed sends no CORS header)
                ?symbol=RELIANCE.NS            whole history, plus splits and dividends
                ?symbol=^NSEI&since=YYYY-MM-DD only newer sessions, to top up the baseline
api/search.js   symbol lookup over NSE's equity master file plus live search
                ?q=reliance
```

`index.html` opens on the NIFTY 50 using its embedded dataset, so that view works offline with no
server. Selecting anything else fetches it from `api/quote`. New calendar years appear on their own,
because every year section is derived from the data rather than a hard-coded list.

Deep links work: `#symbol=TCS.NS` opens straight into that instrument.

## Running it

Open `index.html` in a browser. That is the whole thing.

Charting uses Chart.js from a CDN, so the first open needs a connection; if it is unavailable the
page says so and every table and statistic still works.
