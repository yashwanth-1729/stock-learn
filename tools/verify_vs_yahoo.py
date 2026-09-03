"""
Cross-check the harvested NSE bhavcopy database against the bulk feed, per symbol.

There is a catch worth being explicit about: bhavcopy publishes prices AS TRADED,
while the bulk feed serves them SPLIT-ADJUSTED. For any company that has split, the
two therefore disagree before the split date by exactly the split ratio — that is
correct behaviour on both sides, not an error.

So this reports two numbers per symbol:
  since-last-split : the window where both should agree exactly
  whole-history    : includes pre-split days, where a mismatch is expected

Usage: python verify_vs_yahoo.py [N_SYMBOLS]
"""
import datetime, json, os, random, sqlite3, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
DB = os.path.join(DATA, "nse_eod.sqlite")
EPOCH = datetime.date(1970, 1, 1)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Accept": "*/*"}
N = int(sys.argv[1]) if len(sys.argv) > 1 else 25

db = sqlite3.connect(DB)
syms = [r[0] for r in db.execute(
    "SELECT sym FROM px GROUP BY sym HAVING COUNT(*) > 900 ORDER BY COUNT(*) DESC LIMIT 400")]
random.Random(7).shuffle(syms)
syms = syms[:N]
print("checking %d symbols against the bulk feed\n" % len(syms), flush=True)


def yahoo(sym):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + sym +
           ".NS?period1=0&period2=%d&interval=1d&events=split" % int(time.time() + 86400))
    d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90))
    r = d["chart"]["result"][0]
    off = r["meta"]["gmtoffset"]
    q = r["indicators"]["quote"][0]
    out = {}
    for i, t in enumerate(r["timestamp"]):
        c = q["close"][i]
        if c is None:
            continue
        out[datetime.datetime.fromtimestamp(t + off, datetime.UTC).date()] = round(c, 2)
    splits = sorted(datetime.datetime.fromtimestamp(s["date"] + off, datetime.UTC).date()
                    for s in (r.get("events", {}).get("splits", {}) or {}).values())
    return out, splits


hdr = "%-13s %7s  %-22s  %-22s %s" % ("SYMBOL", "DAYS", "SINCE LAST SPLIT", "WHOLE HISTORY", "SPLITS")
print(hdr); print("-" * len(hdr), flush=True)
agg_recent = [0, 0]
agg_all = [0, 0]
failures = []

for sym in syms:
    ours = {EPOCH + datetime.timedelta(d): c
            for d, c in db.execute("SELECT d,c FROM px WHERE sym=?", (sym,))}
    try:
        theirs, splits = yahoo(sym)
    except Exception as e:
        print("%-13s  feed error: %s" % (sym, str(e)[:40]), flush=True)
        continue
    common = sorted(set(ours) & set(theirs))
    if len(common) < 100:
        print("%-13s  only %d overlapping days, skipped" % (sym, len(common)), flush=True)
        continue
    cutoff = max(splits) if splits else datetime.date(1900, 1, 1)

    def rate(days):
        ok = sum(1 for d in days if abs(ours[d] - theirs[d]) <= max(0.02, theirs[d] * 0.001))
        return ok, len(days)

    recent = [d for d in common if d > cutoff]
    r_ok, r_n = rate(recent) if recent else (0, 0)
    a_ok, a_n = rate(common)
    agg_recent[0] += r_ok; agg_recent[1] += r_n
    agg_all[0] += a_ok; agg_all[1] += a_n
    if r_n and r_ok / r_n < 0.98:
        failures.append((sym, r_ok, r_n))
    print("%-13s %7d  %6d/%-6d %6.2f%%  %6d/%-6d %6.2f%%  %d"
          % (sym, len(ours), r_ok, r_n, (r_ok / r_n * 100 if r_n else 0),
             a_ok, a_n, a_ok / a_n * 100, len(splits)), flush=True)

print("\n" + "=" * 70)
if agg_recent[1]:
    print("since last split : %s/%s matched  =  %.3f%%"
          % (format(agg_recent[0], ","), format(agg_recent[1], ","),
             agg_recent[0] / agg_recent[1] * 100))
print("whole history    : %s/%s matched  =  %.3f%%   (pre-split gaps expected)"
      % (format(agg_all[0], ","), format(agg_all[1], ","), agg_all[0] / agg_all[1] * 100))
if failures:
    print("\nsymbols under 98%% on the post-split window:")
    for s, ok, n in failures:
        print("   %-13s %d/%d" % (s, ok, n))
else:
    print("\nno symbol fell below 98% on its post-split window.")
