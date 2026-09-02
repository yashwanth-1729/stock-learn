/**
 * GET /api/quote?symbol=RELIANCE.NS            → whole history for one instrument
 * GET /api/quote?symbol=^NSEI&since=YYYY-MM-DD → only sessions after `since`
 *
 * Works for any NSE (`.NS`) or BSE (`.BO`) listing and for the indices, because the
 * upstream chart API is symbol-agnostic. Exists because that API sends no CORS header,
 * so a browser cannot call it directly.
 *
 * Nothing about a company is hard-coded here. Splits and dividends come back from the
 * feed as dated events, so each instrument carries its own corporate actions.
 *
 * The one exception is NIFTY_PATCH: real NSE index sessions the bulk feed is missing or
 * has blank, every value taken from the exchange's own end-of-day index file
 * (nsearchives.nseindia.com/content/indices/ind_close_all_<DDMMYYYY>.csv). Three are the
 * first trading day of their year, so without them 2016, 2018 and 2019 report the wrong
 * starting price. It applies to ^NSEI only.
 */

const DAY = 86400000;
const NIFTY = '^NSEI';

const NIFTY_PATCH = [
  ['2013-01-01', 5937.65, 5963.9, 5935.2, 5950.85],
  ['2013-11-03', 6332.05, 6342.95, 6311.15, 6317.35],
  ['2014-01-01', 6323.8, 6327.2, 6298.25, 6301.65],
  ['2014-02-17', 6057.1, 6080.65, 6038.3, 6073.3],
  ['2014-03-22', 6497.8, 6502.65, 6481.35, 6494.9],
  ['2014-10-23', 8027.7, 8031.75, 8008.85, 8014.55],
  ['2015-01-01', 8272.8, 8294.7, 8248.75, 8284.0],
  ['2015-02-28', 8913.05, 8941.1, 8751.35, 8901.85],
  ['2015-04-15', 8844.75, 8844.8, 8722.4, 8750.2],
  ['2015-11-11', 7838.8, 7847.95, 7819.1, 7825.0],
  ['2016-01-01', 7938.45, 7972.55, 7909.8, 7963.2],
  ['2016-08-12', 8605.45, 8684.3, 8604.45, 8672.15],
  ['2016-10-30', 8672.35, 8678.25, 8616.25, 8625.7],
  ['2018-01-01', 10531.7, 10537.85, 10423.1, 10435.55],
  ['2019-01-01', 10881.7, 10923.6, 10807.1, 10910.1],
  ['2019-02-13', 10870.55, 10891.65, 10772.1, 10793.65],
  ['2019-03-29', 11625.45, 11630.35, 11570.15, 11623.9],
  ['2019-10-27', 11662.25, 11672.4, 11604.6, 11627.15],
  ['2020-02-01', 11939.0, 12017.35, 11633.3, 11661.85],
  ['2020-11-14', 12823.35, 12828.7, 12749.45, 12780.25],
  ['2023-11-12', 19547.25, 19547.25, 19510.25, 19525.55],
  ['2026-02-01', 25333.75, 25440.9, 24571.75, 24825.45],
  ['2026-08-28', 24122.6, 24188.3, 24076.85, 24175.65],
  ['2026-09-01', 24077.55, 24143.15, 23952.55, 24055.8],
];
const NIFTY_START = '2007-09-17'; // first session the bulk feed has for ^NSEI

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/126.0 Safari/537.36';

function isoOf(ms) {
  const d = new Date(ms);
  return (
    d.getUTCFullYear() +
    '-' + String(d.getUTCMonth() + 1).padStart(2, '0') +
    '-' + String(d.getUTCDate()).padStart(2, '0')
  );
}

async function fetchChart(symbol, fromSec) {
  const to = Math.floor(Date.now() / 1000) + 86400;
  const url =
    'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(symbol) +
    '?period1=' + fromSec + '&period2=' + to + '&interval=1d&events=div%2Csplit';
  const r = await fetch(url, { headers: { 'User-Agent': UA, Accept: '*/*' } });
  if (r.status === 404) throw Object.assign(new Error('unknown symbol'), { code: 404 });
  if (!r.ok) throw new Error('upstream ' + r.status);
  const j = await r.json();
  const res = j && j.chart && j.chart.result && j.chart.result[0];
  if (!res || !res.timestamp || !res.timestamp.length) {
    throw Object.assign(new Error('no price history for this symbol'), { code: 404 });
  }

  const off = (res.meta.gmtoffset || 0) * 1000;
  const q = res.indicators.quote[0];
  const rows = new Map();
  for (let i = 0; i < res.timestamp.length; i++) {
    const o = q.open[i], h = q.high[i], l = q.low[i], c = q.close[i];
    if (o == null || h == null || l == null || c == null) continue;
    if (!(c > 0)) continue;
    rows.set(isoOf(res.timestamp[i] * 1000 + off), [
      +o.toFixed(2), +h.toFixed(2), +l.toFixed(2), +c.toFixed(2),
    ]);
  }

  // Corporate actions, straight from the feed — the per-instrument "special days".
  const ev = res.events || {};
  const splits = Object.values(ev.splits || {})
    .map((s) => [isoOf(s.date * 1000 + off), String(s.splitRatio || '')])
    .sort((a, b) => (a[0] < b[0] ? -1 : 1));
  const dividends = Object.values(ev.dividends || {})
    .map((d) => [isoOf(d.date * 1000 + off), +Number(d.amount).toFixed(4)])
    .sort((a, b) => (a[0] < b[0] ? -1 : 1));

  return { rows, splits, dividends, meta: res.meta };
}

/** Base-36 delta encoding — compact on the wire and cheap for the page to expand. */
function encode(sorted) {
  const p = (x) => Math.round(x * 100);
  const start = sorted[0][0];
  const base = Date.parse(start + 'T00:00:00Z');
  const d = [], c = [], o = [], h = [], l = [];
  let prevDay = null, prevC = 0;
  for (const [iso, v] of sorted) {
    const day = Math.round((Date.parse(iso + 'T00:00:00Z') - base) / DAY);
    d.push((prevDay === null ? day : day - prevDay).toString(36));
    prevDay = day;
    const cc = p(v[3]);
    c.push((cc - prevC).toString(36));
    prevC = cc;
    o.push((p(v[0]) - cc).toString(36));
    h.push((p(v[1]) - cc).toString(36));
    l.push((p(v[2]) - cc).toString(36));
  }
  return {
    base: start, n: sorted.length,
    d: d.join(','), c: c.join(','), o: o.join(','), h: h.join(','), l: l.join(','),
  };
}

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS');
  if (req.method === 'OPTIONS') return res.status(204).end();

  const q = req.query || {};
  const symbol = String(q.symbol || NIFTY).trim().toUpperCase();
  const since = String(q.since || '').slice(0, 10);
  const wantSince = /^\d{4}-\d{2}-\d{2}$/.test(since);

  if (!/^[A-Z0-9^.&-]{1,24}$/.test(symbol)) {
    return res.status(400).json({ error: 'bad symbol' });
  }

  const isNifty = symbol === NIFTY;

  try {
    const fromSec = wantSince
      ? Math.floor((Date.parse(since + 'T00:00:00Z') - 14 * DAY) / 1000)
      : 0; // 0 = as far back as the feed goes for this instrument

    const { rows, splits, dividends, meta } = await fetchChart(symbol, fromSec);
    if (isNifty) {
      for (const [iso, o, h, l, c] of NIFTY_PATCH) {
        if (!wantSince || iso > since) rows.set(iso, [o, h, l, c]);
      }
    }

    const floor = isNifty && !wantSince ? NIFTY_START : '';
    const sorted = [...rows.entries()]
      .filter(([iso]) => (wantSince ? iso > since : iso >= floor))
      .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));

    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=86400');

    if (wantSince) {
      return res.status(200).json({
        symbol,
        last: sorted.length ? sorted[sorted.length - 1][0] : since,
        rows: sorted.map(([iso, v]) => [iso, v[0], v[1], v[2], v[3]]),
      });
    }

    if (sorted.length < 2) {
      return res.status(404).json({ error: 'not enough price history for ' + symbol });
    }
    if (isNifty && sorted.length < 4000) {
      throw new Error('NIFTY series unexpectedly short: ' + sorted.length);
    }

    return res.status(200).json({
      symbol,
      name: meta.longName || meta.shortName || symbol,
      exchange: meta.fullExchangeName || meta.exchangeName || '',
      currency: meta.currency || 'INR',
      type: meta.instrumentType || '',
      first: sorted[0][0],
      last: sorted[sorted.length - 1][0],
      splits,
      dividends,
      series: encode(sorted),
    });
  } catch (err) {
    const code = err && err.code === 404 ? 404 : 502;
    res.setHeader('Cache-Control', 'no-store');
    return res.status(code).json({ error: String((err && err.message) || err) });
  }
};
