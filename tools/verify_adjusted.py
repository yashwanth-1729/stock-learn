"""
Prove the derived adjustment factors actually work.

verify_vs_yahoo.py compares RAW bhavcopy against the adjusted reference, so any company
with a corporate action legitimately disagrees before that action. This script applies
the factors from derive_adjustments.py first, then makes the same comparison. If the
derivation is right, the symbols that previously failed should now match like the rest.

The point of the exercise: once these factors are stored, the exchange's own prices are
self-sufficient and the reference feed is no longer needed to serve charts.

Usage: python verify_adjusted.py [N_SYMBOLS]
"""
import datetime, json, os, random, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
DB = os.path.join(DATA, "nse_eod.sqlite")
ADJ_F = os.path.join(DATA, "adjustments.json")
CACHE = os.path.join(DATA, "ref_cache")
EPOCH = datetime.date(1970, 1, 1)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40

with open(ADJ_F, encoding="utf-8") as f:
    ADJ = json.load(f)
db = sqlite3.connect(DB)


def factor_series(sym):
    steps = (ADJ.get(sym) or {}).get("steps") or []
    return sorted(((datetime.date.fromisoformat(d) - EPOCH).days, float(v)) for d, v in steps)


def factor_on(marks, d):
    f = 1.0
    for md, mf in marks:
        if d >= md:
            f = mf
        else:
            break
    return f if f > 0 else 1.0


def reference(sym):
    p = os.path.join(CACHE, sym + ".json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        raw = json.load(f)
    return {datetime.date.fromisoformat(k): v for k, v in raw.items()}


cands = [s for s in ADJ if os.path.exists(os.path.join(CACHE, s + ".json"))]
withact = [s for s in cands if (ADJ[s].get("steps"))]
without = [s for s in cands if not ADJ[s].get("steps")]
random.Random(11).shuffle(withact)
random.Random(11).shuffle(without)
# weight the sample towards symbols that have actions, since those are what is being tested
sample = withact[:max(1, N * 2 // 3)] + without[:max(1, N // 3)]

print("verifying %d symbols (%d with corporate actions, %d without)\n"
      % (len(sample), min(len(withact), N * 2 // 3), min(len(without), N // 3)))
hdr = "%-13s %8s  %-20s  %-20s %s" % ("SYMBOL", "DAYS", "RAW", "ADJUSTED", "ACTIONS")
print(hdr); print("-" * len(hdr))

raw_ok = raw_n = adj_ok = adj_n = 0
worse = []
for sym in sample:
    ours = dict(db.execute("SELECT d,c FROM px WHERE sym=?", (sym,)))
    ref = reference(sym)
    if not ref:
        continue
    marks = factor_series(sym)
    common = sorted(d for d in ref if (d - EPOCH).days in ours)
    if len(common) < 150:
        continue
    r_ok = a_ok = 0
    for d in common:
        di = (d - EPOCH).days
        tol = max(0.02, ref[d] * 0.002)
        if abs(ours[di] - ref[d]) <= tol:
            r_ok += 1
        if abs(ours[di] / factor_on(marks, di) - ref[d]) <= tol:
            a_ok += 1
    raw_ok += r_ok; raw_n += len(common)
    adj_ok += a_ok; adj_n += len(common)
    nact = len([m for m in marks if abs(m[1] - 1) > 1e-9])
    pa = a_ok / len(common) * 100
    if pa < 98:
        worse.append((sym, a_ok, len(common), nact))
    print("%-13s %8d  %6d/%-6d %5.1f%%  %6d/%-6d %5.1f%%  %d"
          % (sym, len(ours), r_ok, len(common), r_ok / len(common) * 100,
             a_ok, len(common), pa, nact))

print("\n" + "=" * 72)
print("raw (as traded)      : %s/%s  =  %.3f%%" % (format(raw_ok, ","), format(raw_n, ","),
                                                   raw_ok / max(raw_n, 1) * 100))
print("after adjustment     : %s/%s  =  %.3f%%" % (format(adj_ok, ","), format(adj_n, ","),
                                                   adj_ok / max(adj_n, 1) * 100))
if worse:
    print("\nstill under 98%:")
    for s, ok, n, a in worse:
        print("   %-13s %d/%d  (%d actions)" % (s, ok, n, a))
else:
    print("\nevery symbol in the sample is at or above 98% once adjusted.")
