# NIFTY 50 Historical Analysis

A visual historical study of India's NIFTY 50 index — how it actually behaved, one calendar year
at a time. Not a trading dashboard: no RSI, no MACD, no Bollinger bands. Just the real daily record.

**4,673 verified trading sessions · 17 September 2007 → 1 September 2026**

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

Daily open/high/low/close for the NIFTY 50 **price** index, reconciled from two sources:

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

### Known limits, stated rather than papered over

- **History starts in September 2007.** No reachable source publishes reliable daily NIFTY closes
  before then — NSE's archive does not go back that far and the index provider's bulk endpoint is
  closed. The record begins where the real data begins.
- **Granularity is one row per session.** Intraday history is not available over a span this long,
  so date pickers work in whole days.
- **A few Saturdays and Sundays appear.** These are real, officially settled NSE sessions — Diwali
  Muhurat trading and Union Budget weekend sittings — kept so the data matches the exchange calendar.
- **Sessions before 2013 rest on the bulk feed alone**, since NSE's archive files do not exist for them.
- This is a **price index**: it excludes dividends and so understates an investor's actual return.
- Nothing here is investment advice. It is a record of what already happened.

## Layout

```
index.html      the whole study tool — self-contained, opens straight off disk
api/nifty.js    serverless endpoint; proxies the upstream feed (it sends no CORS header)
                ?full=1            the entire verified series
                ?since=YYYY-MM-DD  only newer sessions, to top up the embedded baseline
```

`index.html` ships with the dataset embedded, so it works offline with no server. Deployed, it also
calls `api/nifty` to pick up sessions that have happened since the build — new years appear on their
own, because every year section is derived from the data rather than a hard-coded list.

## Running it

Open `index.html` in a browser. That is the whole thing.

Charting uses Chart.js from a CDN, so the first open needs a connection; if it is unavailable the
page says so and every table and statistic still works.
