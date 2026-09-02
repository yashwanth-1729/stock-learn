/**
 * GET /api/search?q=reliance → matching Indian instruments
 *
 * Two sources, merged and de-duplicated:
 *   1. NSE's own equity master list (EQUITY_L.csv, ~2,500 listed companies), fetched once
 *      per warm instance and cached. This is the authoritative roll of what trades on NSE.
 *   2. The upstream symbol search, which also reaches BSE listings and the indices.
 *
 * No company list is written into this file — it is fetched from the exchange.
 */

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/126.0 Safari/537.36';

/** A handful of indices, which are not in the equity list but are what most people want first. */
const INDICES = [
  ['^NSEI', 'NIFTY 50', 'NSE index'],
  ['^NSEBANK', 'NIFTY BANK', 'NSE index'],
  ['^CNXIT', 'NIFTY IT', 'NSE index'],
  ['^CNXAUTO', 'NIFTY AUTO', 'NSE index'],
  ['^CNXPHARMA', 'NIFTY PHARMA', 'NSE index'],
  ['^CNXFMCG', 'NIFTY FMCG', 'NSE index'],
  ['^CNXMETAL', 'NIFTY METAL', 'NSE index'],
  ['^NSMIDCP', 'NIFTY MIDCAP 100', 'NSE index'],
  ['^BSESN', 'S&P BSE SENSEX', 'BSE index'],
];

let NSE_CACHE = null;
let NSE_AT = 0;
const TTL = 12 * 3600 * 1000;

async function nseList() {
  if (NSE_CACHE && Date.now() - NSE_AT < TTL) return NSE_CACHE;
  try {
    const r = await fetch(
      'https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv',
      { headers: { 'User-Agent': UA, Accept: '*/*', Referer: 'https://www.nseindia.com/' } }
    );
    if (!r.ok) throw new Error('nse ' + r.status);
    const txt = await r.text();
    const out = [];
    const lines = txt.split(/\r?\n/);
    for (let i = 1; i < lines.length; i++) {
      const p = lines[i].split(',');
      if (p.length < 3) continue;
      const sym = (p[0] || '').trim();
      const name = (p[1] || '').trim();
      if (!sym || !name) continue;
      if ((p[2] || '').trim() !== 'EQ') continue; // regular equity series only
      out.push([sym + '.NS', name, 'NSE']);
    }
    if (out.length > 500) { NSE_CACHE = out; NSE_AT = Date.now(); }
    return NSE_CACHE || out;
  } catch (e) {
    return NSE_CACHE || [];
  }
}

async function upstream(q) {
  try {
    const r = await fetch(
      'https://query1.finance.yahoo.com/v1/finance/search?quotesCount=12&newsCount=0&q=' +
        encodeURIComponent(q),
      { headers: { 'User-Agent': UA, Accept: '*/*' } }
    );
    if (!r.ok) return [];
    const j = await r.json();
    return (j.quotes || [])
      .filter((x) => /\.(NS|BO)$/.test(x.symbol || '') || /^\^/.test(x.symbol || ''))
      .map((x) => [
        x.symbol,
        x.longname || x.shortname || x.symbol,
        x.symbol.endsWith('.BO') ? 'BSE' : x.symbol.startsWith('^') ? 'Index' : 'NSE',
      ]);
  } catch (e) {
    return [];
  }
}

function score(q, sym, name) {
  const s = sym.replace(/\.(NS|BO)$/, '').toUpperCase();
  const n = name.toUpperCase();
  if (s === q) return 0;
  if (s.startsWith(q)) return 1;
  if (n.startsWith(q)) return 2;
  if (n.includes(' ' + q)) return 3;
  if (s.includes(q)) return 4;
  if (n.includes(q)) return 5;
  return 99;
}

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS');
  if (req.method === 'OPTIONS') return res.status(204).end();

  const q = String((req.query && req.query.q) || '').trim().toUpperCase().slice(0, 40);
  if (q.length < 1) {
    res.setHeader('Cache-Control', 's-maxage=3600');
    return res.status(200).json({ results: INDICES.map(([s, n, e]) => ({ symbol: s, name: n, exchange: e })) });
  }

  try {
    const [nse, up] = await Promise.all([nseList(), upstream(q)]);
    const pool = INDICES.concat(nse).concat(up);

    const seen = new Set();
    const hits = [];
    for (const [sym, name, exch] of pool) {
      if (seen.has(sym)) continue;
      const sc = score(q, sym, name);
      if (sc === 99) continue;
      seen.add(sym);
      hits.push({ symbol: sym, name, exchange: exch, _s: sc });
    }
    hits.sort((a, b) => a._s - b._s || a.symbol.length - b.symbol.length);
    const results = hits.slice(0, 25).map(({ _s, ...r }) => r);

    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=86400');
    return res.status(200).json({ results, listed: nse.length });
  } catch (err) {
    res.setHeader('Cache-Control', 'no-store');
    return res.status(502).json({ error: String((err && err.message) || err), results: [] });
  }
};
