"""
Derive corporate-action adjustment factors for the harvested bhavcopy data.

Bhavcopy publishes prices AS TRADED. Charts need them ADJUSTED, or a 2:1 split
renders as a 50% crash. The adjustment is normally bought from a corporate-actions
vendor. It does not have to be.

For any symbol, ratio(d) = astraded(d) / adjusted(d) is a step function: flat between
corporate actions, stepping on the day one takes effect, and equal to 1 at the present.
So the whole factor timeline can be recovered by comparing the two series ONCE and
segmenting the ratio — which captures splits, bonuses, rights issues and demergers
alike, without needing to know which happened.

The reference series is only ever used to calibrate. Once the factors are stored, the
exchange's own prices become self-sufficient.

Output: adjustments.json  {"SYMBOL": {"steps": [[iso_from, factor], ...], "checked": N}}
Applying it: adjusted(d) = astraded(d) / factor_in_force_on(d)

Usage: python derive_adjustments.py [--min-days N] [--limit N] [--symbols A,B,C]
"""
import datetime, json, os, sqlite3, statistics, sys, time
import urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
DB = os.path.join(DATA, "nse_eod.sqlite")
CACHE = os.path.join(DATA, "ref_cache")
OUT = os.path.join(DATA, "adjustments.json")  # overridable with --out
os.makedirs(CACHE, exist_ok=True)

EPOCH = datetime.date(1970, 1, 1)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Accept": "*/*"}
GAP = 0.8                    # polite pacing against the reference feed
STEP_TOL_MIN = 0.003         # floor: never treat a move under 0.3% as an action
STEP_TOL_MAX = 0.030         # ceiling: keep very noisy penny stocks from inventing them
CONFIRM = 5                  # sessions compared either side of a candidate break

def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

MIN_DAYS = int(arg("--min-days", 250))
OUT = arg("--out", OUT)
LIMIT = int(arg("--limit", 0))
ONLY = [s.strip().upper() for s in arg("--symbols", "").split(",") if s.strip()]

_last = [0.0]


def reference(sym):
    """Adjusted daily closes for one symbol, cached on disk so re-runs are free."""
    cp = os.path.join(CACHE, sym + ".json")
    if os.path.exists(cp):
        with open(cp, encoding="utf-8") as f:
            raw = json.load(f)
        return {datetime.date.fromisoformat(k): v for k, v in raw.items()}
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + sym +
           ".NS?period1=0&period2=%d&interval=1d" % int(time.time() + 86400))
    delay = 2.0
    for _ in range(5):
        wait = GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
            break
        except urllib.error.HTTPError as e:
            if e.code in (404, 401):
                with open(cp, "w", encoding="utf-8") as f:
                    json.dump({}, f)
                return {}
            time.sleep(delay); delay = min(delay * 2, 60)
        except Exception:
            time.sleep(delay); delay = min(delay * 2, 60)
    else:
        return None
    try:
        r = d["chart"]["result"][0]
        off = r["meta"]["gmtoffset"]
        q = r["indicators"]["quote"][0]
        out = {}
        for i, t in enumerate(r["timestamp"]):
            c = q["close"][i]
            if c is None or c <= 0:
                continue
            out[datetime.datetime.fromtimestamp(t + off, datetime.UTC).date()] = round(c, 4)
    except Exception:
        out = {}
    with open(cp, "w", encoding="utf-8") as f:
        json.dump({k.isoformat(): v for k, v in out.items()}, f)
    return out


def segment(dates, ratios):
    """Split a ratio series into piecewise-constant levels.

    Compares the median of the K days before each point with the median of the K days
    after. Medians rather than single values so one stale or mis-stamped print cannot
    invent a corporate action, and a window on each side so a genuine step is measured
    against settled levels either way.

    The threshold calibrates itself to the symbol. Bhavcopy rounds to paise, so a ₹2,000
    share carries almost no ratio noise while a ₹3 one carries plenty; a fixed cutoff
    would either miss real events on the quiet names or invent them on the noisy ones.
    Reliance's May 2020 rights issue moved the ratio by only 0.95%, which a blanket 1.2%
    cutoff silently merged away — hence measuring the noise instead of assuming it.
    """
    n = len(ratios)
    if n < 2 * CONFIRM + 2:
        return [[dates[0].isoformat(), round(statistics.median(ratios), 6)]] if ratios else []

    jitter = [abs(ratios[i] / ratios[i - 1] - 1) for i in range(1, n) if ratios[i - 1]]
    noise = statistics.median(jitter) if jitter else 0.0
    tol = max(STEP_TOL_MIN, min(STEP_TOL_MAX, noise * 12))

    K = CONFIRM
    cand = []
    for i in range(K, n - K):
        before = statistics.median(ratios[i - K:i])
        after = statistics.median(ratios[i:i + K])
        if before <= 0:
            continue
        score = abs(after / before - 1)
        if score > tol:
            cand.append((i, score))

    breaks = []
    for i, sc in cand:
        if breaks and i - breaks[-1][0] <= K:
            if sc > breaks[-1][1]:
                breaks[-1] = (i, sc)       # keep the sharpest point in a cluster
        else:
            breaks.append((i, sc))

    # The windowed score peaks NEAR the transition, not exactly on it, which would leave
    # a few sessions carrying the neighbouring factor. Snap each break to the day the
    # ratio actually jumps.
    refined = []
    for i, sc in breaks:
        lo, hi = max(1, i - K), min(n, i + K + 1)
        best, best_jump = i, -1.0
        for j in range(lo, hi):
            if ratios[j - 1] <= 0:
                continue
            jump = abs(ratios[j] / ratios[j - 1] - 1)
            if jump > best_jump:
                best_jump, best = jump, j
        if not refined or best > refined[-1]:
            refined.append(best)

    bounds = [0] + refined + [n]
    steps = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a < 1:
            continue
        lv = round(statistics.median(ratios[a:b]), 6)
        if steps and steps[-1][1] and abs(lv / steps[-1][1] - 1) <= tol:
            continue                       # levels that are not really different
        steps.append([dates[a].isoformat(), lv])
    return steps


db = sqlite3.connect(DB)
syms = [r[0] for r in db.execute(
    "SELECT sym FROM px GROUP BY sym HAVING COUNT(*) >= ? ORDER BY sym", (MIN_DAYS,))]
if ONLY:
    syms = [s for s in syms if s in ONLY]
if LIMIT:
    syms = syms[:LIMIT]

existing = {}
if os.path.exists(OUT):
    with open(OUT, encoding="utf-8") as f:
        existing = json.load(f)

print("deriving adjustment factors for %d symbols (%d already done)"
      % (len(syms), sum(1 for s in syms if s in existing)), flush=True)

t0 = time.time()
adjusted_count = 0
done = 0
for n, sym in enumerate(syms, 1):
    if sym in existing:
        continue
    ours = dict(db.execute("SELECT d,c FROM px WHERE sym=?", (sym,)))
    ref = reference(sym)
    if ref is None:
        print("  ! %s reference unavailable, skipped" % sym, flush=True)
        continue
    common = sorted(set(EPOCH + datetime.timedelta(d) for d in ours) & set(ref))
    if len(common) < 120:
        existing[sym] = {"steps": [], "checked": len(common), "note": "insufficient overlap"}
    else:
        ratios = [ours[(d - EPOCH).days] / ref[d] for d in common]
        steps = segment(common, ratios)
        # Normalise so the most recent level is exactly 1.0 — today's prices are as traded.
        tail = steps[-1][1] if steps else 1.0
        if tail and abs(tail - 1) > 1e-9:
            steps = [[d, round(v / tail, 6)] for d, v in steps]
        # Keep the closing 1.0 step: it carries the date the last action takes effect.
        # Dropping it would leave the previous factor applying forever afterwards.
        if len(steps) <= 1:
            steps = []
        existing[sym] = {"steps": steps, "checked": len(common)}
        if steps:
            adjusted_count += 1
    done += 1
    if done % 50 == 0 or n == len(syms):
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(existing, f, separators=(",", ":"), sort_keys=True)
        el = time.time() - t0
        print("  %4d/%d  %-12s  %d with actions  |  %.0fs elapsed, ~%.0fs left"
              % (n, len(syms), sym, adjusted_count, el,
                 el / max(done, 1) * (len(syms) - n)), flush=True)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(existing, f, separators=(",", ":"), sort_keys=True)

withsteps = {k: v for k, v in existing.items() if v.get("steps")}
print("\nDONE  %d symbols mapped | %d carry corporate actions | %.1f KB"
      % (len(existing), len(withsteps), os.path.getsize(OUT) / 1024), flush=True)
print("largest factors seen:", flush=True)
top = sorted(withsteps.items(), key=lambda kv: -max(s[1] for s in kv[1]["steps"]))[:8]
for s, v in top:
    print("   %-13s %s" % (s, " -> ".join("%s@%.4f" % (d, f) for d, f in v["steps"][:4])), flush=True)
