# Owning the data

The pages currently read prices from a bulk feed. That feed is undocumented, rate
limited, and its terms do not permit commercial redistribution — so it cannot sit under
anything you charge for. These scripts build a replacement from NSE's own public files.

## build_bhavcopy.py

Harvests NSE's daily bhavcopy, one file per trading day containing every listed
security, into a local SQLite database.

    python tools/build_bhavcopy.py 2007-09-17 2026-09-02

Result of the first full run: **4,215 symbols, 7,213,372 rows, 4,689 trading days,
17 Sep 2007 → 1 Sep 2026, 501 MB**, in about 34 minutes at ~2.2 requests a second.

Two file formats exist (the layout changed around July 2024) and both are handled.
Columns are matched by NAME, never by position, so a reordering cannot silently shift
prices into the wrong field. Zips are cached and completed days recorded, so a run that
is interrupted resumes exactly where it stopped.

## verify_vs_yahoo.py

Compares the harvested database against the bulk feed, symbol by symbol.

    python tools/verify_vs_yahoo.py 25

**Read the output carefully.** Bhavcopy publishes prices AS TRADED. The bulk feed serves
them ADJUSTED for corporate actions. Where a company has had a split, bonus, rights issue
or demerger, the two disagree before that date by exactly the adjustment factor — both
are correct, they are answering different questions.

On a 22-symbol sample, symbols with no outstanding adjustment matched **99.5–100%**.
The four that did not were all explained by a corporate action the feed adjusts for:

| Symbol    | Ratio step        | On         | Cause                        |
|-----------|-------------------|------------|------------------------------|
| SIEMENS   | 1.704 → 1.000     | 2025-04-07 | Siemens Energy demerger      |
| IDEA      | 1.658 → 1.000     | 2019-04-01 | rights issue                 |
| TATACOMM  | 1.611 → 1.000     | 2019-10-01 | demerger                     |
| SMSPHARMA | 10.547 → 1.055 → 1.000 | 2015-12-17, 2017-07-07 | 10:1 split, then a bonus |

The ratios are clean constants that step on a single day. That is the useful part: the
adjustment factors are fully recoverable, so they can be derived once and then applied
forever without depending on the feed.

## export_symbols.py

Writes per-symbol JSON in the same base-36 delta encoding `index.html` already decodes,
so the front end needs no changes to read exchange-sourced data.

    python tools/export_symbols.py data/export --min-days 250 [--splits splits.json]

First run: **3,453 symbols, 112 MB, 33 KB average per symbol.**

Without a splits file the output is AS TRADED and is labelled so. Drawn raw, a 2:1 split
renders as a 50% crash — which is why the adjustment step above is not optional before
this becomes the serving source.

## Where the data lives

`data/` is gitignored. It holds the SQLite database, the export and the zip cache
(~960 MB together), all rebuildable from these scripts.

## Still to do before this replaces the feed

1. Derive adjustment factors per symbol from the ratio steps, and store them.
2. Point `api/quote.js` at the exported files, keeping the feed as a fallback.
3. Put the export behind object storage or an edge database rather than the git repo —
   112 MB of static JSON is fine for a CDN and much too heavy for a deployment bundle.
