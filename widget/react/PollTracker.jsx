/*
  The Times poll tracker: headline widget as a React component.
  A port of widget/poll_tracker_block.html; it looks and behaves the same, and reads the same outputs/widget.json.

    import PollTracker from './PollTracker';
    <PollTracker />                                  // reads widget.json live from GitHub
    <PollTracker src="/data/widget.json" />          // or from another URL
    <PollTracker data={widgetJson} />                // or from data you already have (no fetch)

  Needs React 16.8+ and nothing else. The styles are inside the component and scoped to .tt-poll-tracker.
  Keep this file ASCII-only, like the blocks: special characters are written as \u escapes.
*/
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

export const DEFAULT_SRC = 'https://raw.githubusercontent.com/times/times-poll-tracker/main/outputs/widget.json';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const NDASH = '–', UP = '▲', DOWN = '▼', MINUS = '−', APOS = '’';
const SHORT = { LAB: 'Lab', CON: 'Con', REF: 'Ref', LD: 'LD', GRN: 'Grn' };
const NOUN = { LAB: 'Labour', CON: 'The Conservatives', REF: 'Reform UK', LD: 'The Lib Dems', GRN: 'The Greens' };
const SING = { LAB: true, REF: true };
const WIDE = 680, MID = 940, NARROW = 560, NARROW_POLLS = 8;   // container widths (px); polls shown when not side by side
const SVG_FONT = 'Times Roboto, Roboto, Roboto-Regular, Arial, sans-serif';
const DAY = 864e5;

function pd(s) { const p = s.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])); }
function fdate(s, yr) { const d = pd(s); return d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()] + (yr ? ' ' + d.getUTCFullYear() : ''); }
function frange(a, b) {
  if (!a || a === b) return fdate(b);
  const x = pd(a), y = pd(b);
  return x.getUTCMonth() === y.getUTCMonth() ? x.getUTCDate() + NDASH + fdate(b) : fdate(a) + ' ' + NDASH + ' ' + fdate(b);
}
function chg(v) { return v > 0.05 ? UP + ' +' + v.toFixed(1) : v < -0.05 ? DOWN + ' ' + v.toFixed(1).replace('-', MINUS) : 'No change'; }
function headline(ps) {
  const a = ps[0], b = ps[1], lead = a.share - b.share, r = Math.round(lead);
  if (lead < 1) return NOUN[a.code] + ' and ' + NOUN[b.code].replace('The ', 'the ') + ' are neck and neck';
  return NOUN[a.code] + (SING[a.code] ? ' leads' : ' lead') + ' by ' + r + (r === 1 ? ' point' : ' points');
}

// Width of an element, kept up to date as it resizes.
function useWidth(ref) {
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    setW(el.clientWidth);
    let raf = 0;
    const update = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => setW(el.clientWidth)); };
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', update);
      return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', update); };
    }
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, [ref]);
  return w;
}

function buildChart(D, range, W, mid) {
  const small = W < 620, H = mid ? 280 : W < 420 ? 200 : 250;
  const padL = 28, padR = small ? 44 : 100, padT = 10, padB = 24;
  const dates = D.series.dates, n = dates.length;
  let i0 = 0;
  if (range !== 'all') { const cut = pd(D.latest_date).getTime() - 365 * DAY; while (i0 < n - 1 && pd(dates[i0]).getTime() < cut) i0++; }
  const ds = dates.slice(i0), ts = ds.map((d) => pd(d).getTime()), t0 = ts[0], t1 = ts[ts.length - 1];
  const vals = [].concat(...D.parties.map((p) => D.series[p.code].slice(i0)));
  const lo = Math.max(0, Math.floor((Math.min(...vals) - 1) / 5) * 5), hi = Math.ceil((Math.max(...vals) + 1) / 5) * 5;
  const X = (t) => padL + (t - t0) / ((t1 - t0) || 1) * (W - padL - padR);
  const Y = (v) => padT + (hi - v) / (hi - lo) * (H - padT - padB);

  const grid = [];
  for (let g = lo; g <= hi; g += 5) grid.push(g);

  const ticks = [], d0 = pd(ds[0]), d1 = pd(ds[ds.length - 1]), step = range === 'all' ? (small ? 6 : 3) : (small ? 3 : 2);
  for (let m = new Date(Date.UTC(d0.getUTCFullYear(), d0.getUTCMonth() + 1, 1)); m <= d1; m = new Date(Date.UTC(m.getUTCFullYear(), m.getUTCMonth() + 1, 1))) {
    if (m.getUTCMonth() % step) continue;
    ticks.push({ x: X(m.getTime()), label: MONTHS[m.getUTCMonth()] + (m.getUTCMonth() < step ? ' ' + m.getUTCFullYear() : '') });
  }

  const lines = D.parties.map((p) => ({
    p,
    points: D.series[p.code].slice(i0).map((v, i) => X(ts[i]).toFixed(1) + ',' + Y(v).toFixed(1)).join(' '),
    endY: Y(D.series[p.code][n - 1]),
  }));
  // End labels, nudged down so they don't overlap.
  const labels = lines.map((l) => ({ p: l.p, y: l.endY })).sort((a, b) => a.y - b.y);
  for (let k = 1; k < labels.length; k++) if (labels[k].y - labels[k - 1].y < 15) labels[k].y = labels[k - 1].y + 15;

  return { W, H, small, padL, padR, padT, padB, i0, ds, ts, t0, t1, lo, hi, X, Y, grid, ticks, lines, labels, axisY: H - padB };
}

export default function PollTracker({ src = DEFAULT_SRC, data: dataProp = null }) {
  const [fetched, setFetched] = useState(null);
  const [failed, setFailed] = useState(false);
  const [range, setRange] = useState('365');
  const [hover, setHover] = useState(null);
  const [tipLeft, setTipLeft] = useState(0);
  const [fontsReady, setFontsReady] = useState(false);
  // Measured layout: set in two passes (reset, then measure) so each measurement sees the default layout.
  const [pass, setPass] = useState(0);
  const [chgBelow, setChgBelow] = useState(false);
  const [stack, setStack] = useState(false);
  const [maxH, setMaxH] = useState(null);
  const [hint, setHint] = useState(false);

  const rootRef = useRef(null), cardsRef = useRef(null), chartRef = useRef(null), wrapRef = useRef(null), tipRef = useRef(null);
  const rootW = useWidth(rootRef), chartW = useWidth(chartRef);
  const D = dataProp || fetched;

  useEffect(() => {
    if (dataProp) return undefined;
    let live = true;
    setFailed(false);
    fetch(src, { cache: 'no-cache' })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((j) => { if (live) setFetched(j); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [src, dataProp]);

  useEffect(() => {
    let live = true;
    if (typeof document !== 'undefined' && document.fonts && document.fonts.ready) document.fonts.ready.then(() => { if (live) setFontsReady(true); });
    return () => { live = false; };
  }, []);

  const wide = rootW >= WIDE, mid = wide && rootW < MID, narrow = rootW > 0 && rootW < NARROW;
  const parties = useMemo(() => (D ? D.parties.slice().sort((a, b) => b.share - a.share) : []), [D]);
  const chart = useMemo(() => (D && chartW ? buildChart(D, range, chartW, mid) : null), [D, range, chartW, mid]);
  const rows = D ? (wide ? D.polls : D.polls.slice(0, NARROW_POLLS)) : [];

  useEffect(() => { setHover(null); }, [range, D]);

  // Pass 1: back to the default layout whenever anything that affects it changes.
  useLayoutEffect(() => {
    setChgBelow(false); setStack(false); setMaxH(null); setPass((p) => p + 1);
  }, [D, rootW, chartW, range, fontsReady]);

  // Pass 2: measure.
  useLayoutEffect(() => {
    if (!D || !cardsRef.current || !wrapRef.current) return;
    // If any party name would be cut short, every card moves its change under the number.
    const over = [].some.call(cardsRef.current.querySelectorAll('.tt-name'), (nm) => {
      let text = 0;
      [].forEach.call(nm.children, (c) => { text += c.getBoundingClientRect().width; });   // the visible name
      return text + 4 > nm.clientWidth;
    });
    setChgBelow(over);
    // If the columns don't fit across (e.g. side by side on a tablet), dates go under the pollster names.
    const wrap = wrapRef.current;
    setStack(wrap.scrollWidth > wrap.clientWidth + 1);
    // Side by side: the table ends level with the chart's axis and scrolls. Otherwise: just the latest few polls.
    if (wide && chart && chartRef.current) {
      const axis = chartRef.current.getBoundingClientRect().top + chart.axisY + 0.5;
      setMaxH(Math.max(160, Math.round(axis - wrap.getBoundingClientRect().top)));
    }
  }, [pass]); // eslint-disable-line react-hooks/exhaustive-deps

  // Pass 3: the "Scroll for more" hint, once the table has its height.
  useLayoutEffect(() => {
    const wrap = wrapRef.current;
    setHint(!!(wrap && wide && wrap.scrollHeight > wrap.clientHeight + 2));
  }, [maxH, stack, wide, rows.length, pass]);

  // Keep the tooltip inside the chart.
  useLayoutEffect(() => {
    if (hover == null || !chart || !tipRef.current) return;
    const x = chart.X(chart.ts[hover]);
    setTipLeft(Math.min(Math.max(0, x + 10), chart.W - tipRef.current.offsetWidth));
  }, [hover, chart]);

  function onMove(ev) {
    if (!chart) return;
    const r = chartRef.current.getBoundingClientRect();
    const cx = (ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left;
    const t = chart.t0 + (cx - chart.padL) / (chart.W - chart.padL - chart.padR) * (chart.t1 - chart.t0);
    let best = 0, bd = Infinity;
    chart.ts.forEach((tt, i) => { const dd = Math.abs(tt - t); if (dd < bd) { bd = dd; best = i; } });
    setHover(best);
  }
  const onOut = () => setHover(null);

  const cls = ['tt-poll-tracker', wide && 'tt-wide', mid && 'tt-mid', narrow && 'tt-narrow', chgBelow && 'tt-chg-below', stack && 'tt-tbl-stack']
    .filter(Boolean).join(' ');

  return (
    <div className={cls} ref={rootRef}>
      <style>{CSS}</style>
      <h2 className="tt-title">{parties.length > 1 ? headline(parties) : 'Westminster voting intention'}</h2>
      <p className="tt-sub">
        {D ? 'The Times average of Westminster voting intention polls, with change over 30 days'
          : failed ? 'The poll tracker couldn' + APOS + 't load just now.' : 'Loading the latest polls…'}
      </p>

      <div className="tt-cards" ref={cardsRef}>
        {parties.map((p) => (
          <div key={p.code} className="tt-card" style={{ '--c': p.colour, '--t': p.text_colour }}
            aria-label={p.name + ', ' + p.share.toFixed(1) + ' per cent; change over 30 days ' + p.change_30d.toFixed(1) + ' points'}>
            <div className="tt-name"><span className="tt-l">{p.name}</span><span className="tt-s">{SHORT[p.code]}</span></div>
            <div className="tt-chg">{chg(p.change_30d)}</div>
            <div className="tt-big">{p.share.toFixed(1)}<small>%</small></div>
          </div>
        ))}
      </div>

      {D && D.moving && D.moving.length > 0 && (
        <div className="tt-moving"><b>Polls moving</b><span>{D.moving.map((m) => m.sentence).join('. ') + '.'}</span></div>
      )}

      <div className="tt-main">
        <div className="tt-col">
          <div className="tt-bar">
            <p className="tt-label">Poll average</p>
            <div className="tt-toggle" role="group" aria-label="Chart period">
              <button type="button" aria-pressed={range === '365'} onClick={() => setRange('365')}>Past year</button>
              <button type="button" aria-pressed={range === 'all'} onClick={() => setRange('all')}
                title="Since the July 2024 general election">Since 2024</button>
            </div>
          </div>
          <div className="tt-chart" ref={chartRef}>
            {chart && <Chart c={chart} hover={hover} onMove={onMove} onOut={onOut} />}
            {chart && hover != null && (
              <div className="tt-tip" ref={tipRef} style={{ display: 'block', left: tipLeft + 'px' }}>
                <b>{(hover === chart.ds.length - 1 ? 'Latest, ' : 'Week to ') + fdate(chart.ds[hover], true)}</b>
                {D.parties.map((p) => ({ p, v: D.series[p.code][chart.i0 + hover] }))
                  .sort((a, b) => b.v - a.v)
                  .map((o) => (
                    <React.Fragment key={o.p.code}>
                      <br /><i style={{ background: o.p.colour }} />{o.p.name + ' ' + o.v.toFixed(1) + '%'}
                    </React.Fragment>
                  ))}
              </div>
            )}
          </div>
        </div>

        <div className="tt-col">
          <div className="tt-tbl-head">
            <p className="tt-label">Latest polls</p>
            <span className="tt-hint" style={hint ? undefined : { display: 'none' }}>Scroll for more</span>
          </div>
          <div className="tt-tbl-wrap" ref={wrapRef} style={maxH != null ? { maxHeight: maxH + 'px' } : undefined}>
            <table>
              {D && (
                <thead>
                  <tr>
                    <th scope="col">Pollster</th>
                    {D.parties.map((p) => <th key={p.code} scope="col"><i style={{ background: p.colour }} />{SHORT[p.code]}</th>)}
                  </tr>
                </thead>
              )}
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.pollster_id + r.fieldwork_end + i}>
                    <td>{r.pollster}<span className="tt-date">{frange(r.fieldwork_start, r.fieldwork_end)}</span></td>
                    {D.parties.map((p) => <td key={p.code}>{r.shares[p.code] == null ? NDASH : r.shares[p.code]}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

function Chart({ c, hover, onMove, onOut }) {
  const { W, H, padL, padR, padT, padB, X, Y, lo, hi, t1, ds } = c;
  const hx = hover == null ? 0 : X(c.ts[hover]);
  return (
    <svg viewBox={'0 0 ' + W + ' ' + H} role="img"
      aria-label={'Line chart of the Times poll average by party, ' + fdate(ds[0], true) + ' to ' + fdate(ds[ds.length - 1], true)}>
      {c.grid.map((g) => (
        <g key={'g' + g}>
          <line x1={padL} x2={W - padR + 4} y1={Y(g)} y2={Y(g)} stroke={g === lo ? '#000' : '#e4e4e4'} />
          <text x={padL - 6} y={Y(g) + 4} textAnchor="end" fontSize="12" fill="#717171" fontFamily={SVG_FONT}>{g + (g === hi ? '%' : '')}</text>
        </g>
      ))}
      {c.ticks.map((t) => (
        <g key={'t' + t.label + t.x}>
          <line x1={t.x} x2={t.x} y1={Y(lo)} y2={Y(lo) + 4} stroke="#000" />
          <text x={t.x} y={H - 6} textAnchor="middle" fontSize="12" fill="#717171" fontFamily={SVG_FONT}>{t.label}</text>
        </g>
      ))}
      {c.lines.map((l) => (
        <g key={l.p.code}>
          <polyline points={l.points} fill="none" stroke={l.p.colour} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
          <circle cx={X(t1)} cy={l.endY} r="4" fill={l.p.colour} stroke="#fff" strokeWidth="1.5" />
        </g>
      ))}
      {c.labels.map((e) => (
        <text key={'l' + e.p.code} x={X(t1) + 9} y={e.y + 4} fontSize="13" fontWeight="500" fill={e.p.text_colour} fontFamily={SVG_FONT}>
          {c.small ? SHORT[e.p.code] : e.p.name}
        </text>
      ))}
      <line x1={hx} x2={hx} y1={padT} y2={H - padB} stroke="#717171" strokeDasharray="2 3" visibility={hover == null ? 'hidden' : 'visible'} />
      <rect x={padL} y={padT} width={W - padL - padR} height={H - padT - padB} fill="transparent"
        onMouseMove={onMove} onMouseLeave={onOut} onTouchStart={onMove} onTouchMove={onMove} onTouchEnd={onOut} />
    </svg>
  );
}

const CSS = `
@font-face { font-family: "Times Roboto"; font-style: normal; font-weight: 400; font-display: swap;
  src: url("https://static.dwcdn.net/custom/themes/thetimes/TimesRoboto-Regular.woff2") format("woff2"),
       url("https://static.dwcdn.net/custom/themes/thetimes/TimesRoboto-Regular.woff") format("woff"); }
@font-face { font-family: "Times Roboto"; font-style: normal; font-weight: 500; font-display: swap;
  src: url("https://static.dwcdn.net/custom/themes/thetimes/TimesRoboto-Medium.woff2") format("woff2"),
       url("https://static.dwcdn.net/custom/themes/thetimes/TimesRoboto-Medium.woff") format("woff"); }
@font-face { font-family: "Times Roboto"; font-style: normal; font-weight: 700; font-display: swap;
  src: url("https://static.dwcdn.net/custom/themes/thetimes/TimesRoboto-Bold.woff2") format("woff2"),
       url("https://static.dwcdn.net/custom/themes/thetimes/TimesRoboto-Bold.woff") format("woff"); }
/* On thetimes.com the page's own "Times Modern" (bold) and "Times Digital W04 Regular" are used first.
   Those files are served only to Times sites, so elsewhere the public Times Modern Regular stands in. */
@font-face { font-family: "TT Times Modern"; font-style: normal; font-weight: 400 700; font-display: swap;
  src: url("https://static.dwcdn.net/custom/themes/thetimes/TimesModern-Regular/TIMESMODERN-REGULAR.woff2") format("woff2"),
       url("https://static.dwcdn.net/custom/themes/thetimes/TimesModern-Regular/TIMESMODERN-REGULAR.woff") format("woff"); }
.tt-poll-tracker {
  --tt-ink: #000; --tt-label: #191919; --tt-muted: #717171; --tt-hint: #8c8c8c; --tt-border: #8c8c8c;
  --tt-rule: #e4e4e4; --tt-dot: #cbcbcb; --tt-chip: #f2f2f2;
  --tt-head: "Times Modern", "TimesModern-Bold", "TT Times Modern", Georgia, "Times New Roman", serif;
  --tt-serif: "Times Digital W04 Regular", "TimesDigitalW04-Regular", "Times Digital", Georgia, "Times New Roman", serif;
  --tt-sans: "Times Roboto", Roboto, "Roboto-Regular", "Helvetica Neue", Arial, sans-serif;
  --tt-dots: linear-gradient(to right, var(--tt-dot) 2px, transparent 2px);
  background: #fff; color: var(--tt-ink); font-family: var(--tt-sans); max-width: 980px; margin: 0 auto;
  padding: 0; box-sizing: border-box; -webkit-text-size-adjust: 100%;
}
.tt-poll-tracker *, .tt-poll-tracker *::before, .tt-poll-tracker *::after { box-sizing: border-box; }
.tt-poll-tracker .tt-title { margin: 0 0 4px; padding: 0; font-family: var(--tt-head); font-size: 24px; font-weight: 700; line-height: 28px; color: var(--tt-ink); }
.tt-poll-tracker .tt-sub { margin: 0 0 14px; font-family: var(--tt-serif); font-size: 16px; line-height: 22px; color: var(--tt-ink); }
.tt-poll-tracker .tt-cards { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; margin: 0 0 18px; }
.tt-poll-tracker .tt-card { display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 6px; align-items: baseline;
  border-top: 3px solid var(--c); padding: 6px 0 0; }
.tt-poll-tracker .tt-name { grid-column: 1; grid-row: 1; font-size: 14px; font-weight: 500; line-height: 18px; color: var(--t);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tt-poll-tracker .tt-name .tt-s { display: none; }
.tt-poll-tracker .tt-big { grid-column: 1 / -1; grid-row: 2; margin: 2px 0 0; font-family: var(--tt-head); font-size: 40px; font-weight: 700; line-height: 46px; color: var(--t);
  font-variant-numeric: lining-nums tabular-nums; white-space: nowrap; }
.tt-poll-tracker .tt-big small { font-size: 20px; font-weight: 700; margin-left: 1px; }
.tt-poll-tracker .tt-chg { grid-column: 2; grid-row: 1; text-align: right; font-size: 12px; line-height: 18px; font-weight: 500;
  color: var(--t); font-variant-numeric: tabular-nums; white-space: nowrap; }
.tt-poll-tracker.tt-chg-below .tt-chg { grid-column: 1 / -1; grid-row: 3; text-align: left; }
.tt-poll-tracker .tt-moving { display: flex; gap: 10px; align-items: baseline; background: var(--tt-chip); padding: 8px 10px; margin: 0 0 16px;
  font-family: var(--tt-serif); font-size: 15px; line-height: 20px; }
.tt-poll-tracker .tt-moving b { font-family: var(--tt-sans); font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; white-space: nowrap; }
.tt-poll-tracker .tt-main { display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; }
.tt-poll-tracker.tt-wide .tt-main { grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); gap: 32px; align-items: start; }
.tt-poll-tracker.tt-mid .tt-main { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 24px; }
.tt-poll-tracker .tt-bar, .tt-poll-tracker .tt-tbl-head { display: flex; justify-content: space-between; align-items: center; gap: 12px;
  min-height: 26px; margin: 0 0 4px; }
.tt-poll-tracker .tt-label { margin: 0; font-size: 15px; font-weight: 500; line-height: 20px; color: var(--tt-label); }
.tt-poll-tracker .tt-toggle { display: inline-flex; border: 1px solid var(--tt-border); }
.tt-poll-tracker .tt-toggle button { font-family: var(--tt-sans); font-size: 12px; line-height: 16px; border: 0; border-radius: 0; background: #fff;
  color: var(--tt-label); padding: 4px 8px; margin: 0; cursor: pointer; white-space: nowrap; }
.tt-poll-tracker .tt-toggle button[aria-pressed="true"] { background: var(--tt-ink); color: #fff; }
.tt-poll-tracker .tt-chart { position: relative; margin: 0; }
.tt-poll-tracker .tt-chart svg { display: block; width: 100%; height: auto; overflow: visible; }
.tt-poll-tracker .tt-tip { position: absolute; top: 6px; display: none; pointer-events: none; background: #fff; border: 1px solid var(--tt-border);
  padding: 6px 9px; font-size: 13px; line-height: 19px; white-space: nowrap; z-index: 3; }
.tt-poll-tracker .tt-tip b { font-weight: 500; }
.tt-poll-tracker .tt-tip i { display: inline-block; width: 9px; height: 9px; margin-right: 5px; }
.tt-poll-tracker .tt-hint { font-size: 12px; line-height: 16px; color: var(--tt-muted); }
.tt-poll-tracker .tt-tbl-wrap { overflow-x: auto; overflow-y: auto; -webkit-overflow-scrolling: touch; border-bottom: 1px solid var(--tt-ink); }
.tt-poll-tracker table { width: 100%; margin: 0; border: 0; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.tt-poll-tracker th, .tt-poll-tracker td { padding: 7px 4px; border: 0; text-align: right; font-size: 14px; line-height: 18px;
  background: var(--tt-dots) left bottom / 4px 1px repeat-x; }
.tt-poll-tracker th:first-child, .tt-poll-tracker td:first-child { text-align: left; padding-left: 0; white-space: nowrap; }
.tt-poll-tracker thead th { white-space: nowrap; font-size: 12px; font-weight: 500; color: var(--tt-muted); vertical-align: bottom;
  position: sticky; top: 0; z-index: 2; background: #fff; box-shadow: inset 0 -1px 0 var(--tt-ink); }
.tt-poll-tracker thead th i { display: inline-block; width: 9px; height: 9px; background: var(--c); margin-right: 4px; vertical-align: -1px; }
.tt-poll-tracker .tt-date { margin-left: 6px; font-size: 12px; color: var(--tt-muted); }
.tt-poll-tracker.tt-tbl-stack .tt-date { display: block; margin-left: 0; line-height: 15px; }
.tt-poll-tracker.tt-narrow .tt-title { font-size: 22px; line-height: 26px; }
.tt-poll-tracker.tt-narrow .tt-sub { font-size: 15px; line-height: 20px; margin-bottom: 12px; }
.tt-poll-tracker.tt-narrow .tt-cards { gap: 8px; margin-bottom: 16px; }
.tt-poll-tracker.tt-narrow .tt-name .tt-l { display: none; }
.tt-poll-tracker.tt-narrow .tt-name .tt-s { display: inline; }
.tt-poll-tracker.tt-narrow .tt-big { font-size: 25px; line-height: 30px; }
.tt-poll-tracker.tt-narrow .tt-big small { font-size: 13px; }
.tt-poll-tracker.tt-narrow .tt-chg { font-size: 11px; }
.tt-poll-tracker.tt-narrow th, .tt-poll-tracker.tt-narrow td { padding: 6px 2px; font-size: 13px; }
.tt-poll-tracker.tt-narrow .tt-date { font-size: 11px; margin-left: 4px; }
`;
