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

The ratios are clean constants that step on a single day. That is the useful part, and
`derive_adjustments.py` below acts on it.

## derive_adjustments.py

Recovers the corporate-action factors from the data, so no corporate-actions feed has to
be licensed.

    python tools/derive_adjustments.py --min-days 250

For any symbol `astraded / adjusted` is a step function — flat between actions, stepping
the day one takes effect, 1.0 today. Comparing the two series once and segmenting that
ratio recovers the whole timeline, and it captures splits, bonuses, rights issues and
demergers alike without needing to know which occurred. The reference is used only to
calibrate; afterwards the exchange's own prices stand alone.

Result: **3,453 symbols mapped, 891 carrying corporate actions, 240 KB**. Reference
series are cached, so re-deriving after a change to the algorithm takes under three
minutes and touches the network not at all.

Recovered timelines land on the real events:

| Symbol   | Timeline |
|----------|----------|
| RELIANCE | 8.75 → 4.37 (2009 bonus) → 2.187 (2017 bonus) → 2.167 (2020 rights) → 2.0 (2023 Jio demerger) → 1.0 (2024 bonus) |
| INFY     | 8 → 4 → 2 → 1 (three 1:1 bonuses) |
| WIPRO    | 8.889 → 5.333 → 2.667 → 2.0 → 1.0 |
| MRF      | none — it has never split |

**Three things this got wrong first, all caught by verification rather than by reading
the code:**

1. The trailing 1.0 step was filtered out as uninteresting, which lost the date the last
   action ends and left the previous factor applying forever after.
2. A fixed 1.2% threshold merged away Reliance's May 2020 rights issue, which moved the
   ratio by only 0.95%, stranding 657 sessions on the wrong factor.
3. A single threshold cannot serve every symbol. Chasing noise gave one ETF 16 invented
   "actions", and on one name the adjustment left agreement *worse* than doing nothing.

So the derivation now scores several thresholds against the reference and keeps whichever
reproduces it best — with the unadjusted series competing on equal terms. Adjustment can
only be applied where it demonstrably helps. Symbols whose reference disagrees entirely
(a ticker collision) are marked `unverified` rather than quietly adjusted.

## verify_adjusted.py

Applies the factors and repeats the comparison.

    python tools/verify_adjusted.py 60

On a 60-symbol sample weighted towards names with actions: **52.6% raw → 99.4% adjusted**.
Across all 3,453 symbols the median match is **99.77%**; 125 sit below 98% and 4 are
ticker collisions.

## export_symbols.py

Writes per-symbol JSON in the same base-36 delta encoding `index.html` already decodes,
so the front end needs no changes to read exchange-sourced data.

    python tools/export_symbols.py data/export --min-days 250

**3,453 symbols, 110.6 MB, 32 KB average**, with 891 corporate-action adjusted from
`adjustments.json` automatically. Encoding matches what `index.html` already decodes.

The adjustment holds where it matters. At Reliance's action dates the exported series now
moves −3.06%, −0.56%, +2.12%, −0.12%, +0.49% — ordinary days, rather than the −50%
phantom crashes the raw prices would have drawn.

## Where the data lives

`data/` is gitignored. It holds the SQLite database, the export and the zip cache
(~960 MB together), all rebuildable from these scripts.

## Still to do before this replaces the feed

1. Put the export behind object storage or an edge database rather than the git repo.
   110 MB of static JSON is ideal for a CDN — 32 KB a request — and much too heavy for a
   deployment bundle.
2. Point `api/quote.js` at those files, keeping the feed as a fallback for symbols the
   export does not carry.
3. Schedule a daily `build_bhavcopy.py` run for the newest session, and re-derive factors
   only for symbols whose latest ratio moves.
