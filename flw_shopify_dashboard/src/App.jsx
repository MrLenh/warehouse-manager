import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, PieChart, Pie, Cell, ComposedChart
} from 'recharts';
import { api, authLogin, authMe, clearAuth, getToken, setToken } from './api.js';

/* ── THEME (light only, no dark mode) ─────────────────── */
const T = {
  bg: '#F4F6FB', card: '#FFFFFF', bdr: '#E2E8F0', div: '#F1F4F9',
  sb: '#1A2236', sbh: '#202D44', sba: '#243250', sbt: '#607490', sbat: '#C8D8EE',
  tx: '#1A2236', tx2: '#4A5A70', mu: '#90A0B8',
  pri: '#3B5BDB', prib: '#EEF2FF', pritx: '#1E3A8A',
  grn: '#0D9488', grnb: '#F0FDFA', grntx: '#134E4A',
  red: '#E53E3E', redb: '#FFF5F5', redtx: '#742A2A',
  ora: '#DD6B20', orab: '#FFFAF0', oratx: '#7B341E',
  pur: '#7C3AED', purb: '#FAF5FF', purtx: '#44337A',
  charts: ['#3B5BDB', '#0D9488', '#DD6B20', '#7C3AED', '#E53E3E', '#2F855A'],
  shadow: 'rgba(26,34,54,.08)',
};
window.__T = T;

/* ── UTILS ────────────────────────────────────────────── */
const f$ = n => {
  if (n == null || isNaN(n)) return '—';
  const a = Math.abs(+n), s = +n < 0 ? '-' : '';
  return s + '$' + a.toLocaleString('en-US', { minimumFractionDigits:0, maximumFractionDigits:0 });
};
const f$2 = n => {
  if (n == null || isNaN(n)) return '—';
  const a = Math.abs(+n), s = +n < 0 ? '-' : '';
  return s + '$' + a.toLocaleString('en-US', { minimumFractionDigits:2, maximumFractionDigits:2 });
};
const fN  = n => n == null ? '—' : Math.round(n).toLocaleString('en-US');
const fP  = n => n == null ? '—' : (+n).toFixed(1) + '%';
const fX  = n => n == null ? '—' : (+n).toFixed(2) + 'x';
const fDateTime = d => {
  if (!d) return '—';
  const s = typeof d === 'string' ? d.replace(' ', 'T') : d;
  const dt = new Date(s);
  if (isNaN(dt)) return '—';
  return dt.toLocaleString('en-US', { month:'short', day:'numeric', year:'numeric', hour:'2-digit', minute:'2-digit' });
};
// Safe image src - handles plain URL string, JSON string {"src":"..."}, or already-object
function imgSrc(raw) {
  if (!raw) return null;
  if (typeof raw === 'object') return raw?.src || null;
  if (typeof raw === 'string') {
    if (raw.startsWith('http')) return raw;
    try { const p = JSON.parse(raw); return p?.src || p?.url || null; } catch { return raw; }
  }
  return null;
}
const fDate = d => {
  if (!d) return '—';
  const dt = new Date(typeof d === 'string' && !d.includes('T') ? d + 'T12:00:00' : d);
  return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};
const fDateShort = d => {
  if (!d) return '—';
  const dt = new Date(typeof d === 'string' && !d.includes('T') ? d + 'T12:00:00' : d);
  return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

/* ── BASE STYLES ──────────────────────────────────────── */
const S = {
  card: { background: T.card, border: `1px solid ${T.bdr}`, borderRadius: 10 },
  th: { padding: '8px 12px', textAlign: 'left', fontSize: 12, fontWeight: 700, color: T.mu, textTransform: 'uppercase', letterSpacing: '.5px', background: T.div, borderBottom: `1px solid ${T.bdr}`, whiteSpace: 'nowrap', position: 'sticky', top: 0, zIndex: 1 },
  td: { padding: '9px 12px', borderBottom: `1px solid ${T.div}`, fontSize: 14, color: T.tx2, verticalAlign: 'middle' },
  inp: { padding: '7px 10px', border: `1px solid ${T.bdr}`, borderRadius: 6, background: T.div, color: T.tx, fontSize: 14, fontFamily: 'inherit', outline: 'none' },
  sel: { padding: '7px 10px', border: `1px solid ${T.bdr}`, borderRadius: 6, background: T.div, color: T.tx2, fontSize: 14, fontFamily: 'inherit', outline: 'none' },
  btn: { padding: '7px 14px', border: 'none', borderRadius: 6, background: T.pri, color: '#fff', fontSize: 14, fontFamily: 'inherit', cursor: 'pointer' },
  btnO: { padding: '7px 14px', border: `1px solid ${T.bdr}`, borderRadius: 6, background: T.card, color: T.tx2, fontSize: 14, fontFamily: 'inherit', cursor: 'pointer' },
};

/* ── MINI COMPONENTS ──────────────────────────────────── */
/* Image preview modal */
function ImageModal({ src, onClose }) {
  if (!src) return null;
  return (
    <div onClick={onClose} style={{ position:'fixed', top:0,left:0,right:0,bottom:0,
      background:'rgba(0,0,0,.75)', zIndex:9999, display:'flex',
      alignItems:'center', justifyContent:'center', cursor:'zoom-out' }}>
      <img src={src} style={{ maxWidth:'80vw', maxHeight:'80vh', borderRadius:10,
        boxShadow:'0 8px 40px rgba(0,0,0,.5)', objectFit:'contain' }} alt="preview"/>
      <button onClick={onClose} style={{ position:'absolute', top:20, right:24,
        background:'rgba(255,255,255,.15)', border:'none', color:'#fff',
        fontSize:28, cursor:'pointer', borderRadius:'50%', width:40, height:40,
        display:'flex', alignItems:'center', justifyContent:'center' }}>×</button>
    </div>
  );
}

function Spinner() {
  return (
    <div style={{ display:'flex', alignItems:'center', justifyContent:'center', padding: 60 }}>
      <div style={{ width:28, height:28, border:`3px solid ${T.bdr}`, borderTopColor:T.pri, borderRadius:'50%', animation:'spin .7s linear infinite' }}/>
    </div>
  );
}
function Err({ msg }) {
  return msg ? <div style={{ background:T.redb, color:T.redtx, padding:'10px 14px', borderRadius:8, marginBottom:12, fontSize:13 }}>Error: {msg}</div> : null;
}

/* Delta badge with tooltip showing compare period */
function DeltaBadge({ v, label, compareLabel }) {
  const [tip, setTip] = useState(false);
  if (v == null) return null;
  const up = v > 0;
  const style = { fontSize:11, fontWeight:700, padding:'2px 6px', borderRadius:4,
    background: up ? T.grnb : T.redb, color: up ? T.grntx : T.redtx,
    cursor: compareLabel ? 'help' : 'default', position:'relative', display:'inline-block' };
  return (
    <span style={style}
      onMouseEnter={() => setTip(true)}
      onMouseLeave={() => setTip(false)}>
      {v > 0 ? '+' : ''}{v.toFixed(1)}%
      {tip && compareLabel && (
        <span style={{ position:'absolute', bottom:'120%', left:'50%', transform:'translateX(-50%)',
          background:T.tx, color:'#fff', fontSize:11, padding:'4px 8px', borderRadius:5,
          whiteSpace:'nowrap', zIndex:100, pointerEvents:'none' }}>
          vs {compareLabel}
        </span>
      )}
    </span>
  );
}

function KpiCard({ label, value, delta: dv, sub, color, compareLabel, tooltip }) {
  const [showTip, setShowTip] = useState(false);
  return (
    <div style={{ ...S.card, padding:'14px 16px', position:'relative' }}>
      <div style={{ display:'flex', alignItems:'center', gap:5, marginBottom:8, cursor: tooltip ? 'help' : 'default' }}
        onMouseEnter={() => setShowTip(true)} onMouseLeave={() => setShowTip(false)}>
        <div style={{ fontSize:11, fontWeight:700, color:T.mu, textTransform:'uppercase', letterSpacing:'.5px' }}>{label}</div>
        {tooltip && <span style={{ fontSize:11, color:T.mu }}>?</span>}
        {showTip && tooltip && (
          <div style={{ position:'absolute', top:'100%', left:0, background:T.tx, color:'#fff',
            fontSize:11.5, padding:'6px 10px', borderRadius:6, zIndex:100, maxWidth:220, lineHeight:1.5, marginTop:4 }}>
            {tooltip}
          </div>
        )}
      </div>
      <div style={{ fontSize:22, fontWeight:700, color: color||T.tx, letterSpacing:'-.4px', fontVariantNumeric:'tabular-nums', marginBottom:5 }}>
        {value}
      </div>
      <div style={{ fontSize:12, display:'flex', alignItems:'center', gap:6, color:T.mu, flexWrap:'wrap' }}>
        {dv != null && <DeltaBadge v={dv} compareLabel={compareLabel} />}
        {sub && <span>{sub}</span>}
      </div>
    </div>
  );
}

function KpiGrid({ children, cols=4 }) {
  return <div style={{ display:'grid', gridTemplateColumns:`repeat(${cols},1fr)`, gap:10, marginBottom:14 }}>{children}</div>;
}

function Card({ children, style={}, p=16 }) {
  return <div style={{ ...S.card, padding:p, marginBottom:12, ...style }}>{children}</div>;
}

function CardTitle({ children, right }) {
  return (
    <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 }}>
      <div style={{ fontSize:14, fontWeight:700, color:T.tx }}>{children}</div>
      {right}
    </div>
  );
}

function TableWrap({ children, style={} }) {
  return <div style={{ ...S.card, overflow:'hidden', marginBottom:12, ...style }}>{children}</div>;
}

function SearchBar({ children }) {
  return <div style={{ padding:'10px 14px', borderBottom:`1px solid ${T.bdr}`, display:'flex', gap:8, alignItems:'center', flexWrap:'wrap' }}>{children}</div>;
}

/* Sortable table header */
function SortTh({ label, col, sortCol, sortDir, onSort }) {
  const active = sortCol === col;
  return (
    <th style={{ ...S.th, cursor:'pointer', userSelect:'none', color: active ? T.pri : T.mu }}
      onClick={() => onSort(col)}>
      {label} {active ? (sortDir==='asc' ? '▲' : '▼') : ''}
    </th>
  );
}

/* Column chooser */
function ColChooser({ allCols, visible, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef();
  useEffect(() => {
    const fn = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', fn);
    return () => document.removeEventListener('mousedown', fn);
  }, []);
  return (
    <div ref={ref} style={{ position:'relative' }}>
      <button onClick={() => setOpen(v=>!v)} style={{ ...S.btnO, padding:'6px 10px', fontSize:12 }}>
        Columns
      </button>
      {open && (
        <div style={{ position:'absolute', right:0, top:'110%', background:T.card,
          border:`1px solid ${T.bdr}`, borderRadius:9, zIndex:50, padding:12,
          minWidth:210, boxShadow:`0 4px 16px ${T.shadow}`, maxHeight:380, overflowY:'auto' }}>
          {allCols.map(c => (
            <label key={c.key} style={{ display:'flex', alignItems:'center', gap:8, padding:'4px 0',
              fontSize:13, color:T.tx2, cursor:'pointer' }}>
              <input type="checkbox" checked={visible.includes(c.key)}
                onChange={e => onChange(c.key, e.target.checked)}
                style={{ accentColor:T.pri }}/>
              {c.label}
            </label>
          ))}
          <button onClick={() => onChange('__reset__')}
            style={{ marginTop:8, width:'100%', padding:'5px 0', border:`1px solid ${T.bdr}`,
              borderRadius:5, background:T.div, color:T.tx2, fontSize:12, cursor:'pointer', fontFamily:'inherit' }}>
            Reset to Default
          </button>
        </div>
      )}
    </div>
  );
}

/* Pager */
function Pager({ page, pages, total, per, onPage }) {
  if (!pages || pages <= 1) return (
    <div style={{ padding:'9px 14px', borderTop:`1px solid ${T.bdr}` }}>
      <span style={{ fontSize:13, color:T.mu }}>{total?.toLocaleString()||0} records</span>
    </div>
  );
  // Build smart page number list: 1 2 3 ... 7 8 9 style
  const buildNums = () => {
    if (pages <= 7) return Array.from({length:pages},(_,i)=>i+1);
    const nums = new Set([1, 2, page-1, page, page+1, pages-1, pages].filter(n=>n>=1&&n<=pages));
    const arr = [...nums].sort((a,b)=>a-b);
    const result = [];
    for (let i=0; i<arr.length; i++) {
      if (i>0 && arr[i]-arr[i-1]>1) result.push('…');
      result.push(arr[i]);
    }
    return result;
  };
  const nums = buildNums();
  const btnS = (cur) => ({ padding:'5px 10px', border:`1px solid ${cur?T.pri:T.bdr}`,
    borderRadius:5, background:cur?T.pri:T.card, color:cur?'#fff':T.tx2, fontSize:13,
    cursor:cur?'default':'pointer', fontFamily:'inherit', fontWeight:cur?700:400 });
  return (
    <div style={{ padding:'9px 14px', display:'flex', justifyContent:'space-between',
      alignItems:'center', borderTop:`1px solid ${T.bdr}` }}>
      <span style={{ fontSize:13, color:T.mu }}>
        Showing {((page-1)*per+1).toLocaleString()}–{Math.min(page*per,total||0).toLocaleString()} of {(total||0).toLocaleString()}
      </span>
      <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
        <button disabled={page<=1} onClick={()=>onPage(page-1)}
          style={{ ...btnS(false), opacity:page<=1?.4:1 }}>Prev</button>
        {nums.map((n,i) => n==='…'
          ? <span key={'e'+i} style={{ padding:'5px 6px', color:T.mu, fontSize:13 }}>…</span>
          : <button key={n} onClick={()=>onPage(n)} style={btnS(n===page)}>{n}</button>
        )}
        <button disabled={page>=pages} onClick={()=>onPage(page+1)}
          style={{ ...btnS(false), opacity:page>=pages?.4:1 }}>Next</button>
      </div>
    </div>
  );
}

/* Status badge */
function StatusBadge({ status }) {
  const map = {
    paid:       { bg:T.grnb, color:T.grntx },
    completed:  { bg:T.grnb, color:T.grntx },
    processing: { bg:T.prib, color:T.pritx },
    refunded:   { bg:T.redb, color:T.redtx },
    cancelled:  { bg:T.div,  color:T.mu },
    'on-hold':  { bg:T.orab, color:T.oratx },
    active:     { bg:T.grnb, color:T.grntx },
    paused:     { bg:T.orab, color:T.oratx },
    draft:      { bg:T.div,  color:T.mu },
  };
  const s = (status||'').toLowerCase().replace(/[-_\s]/g,'');
  const found = Object.entries(map).find(([k]) => k.replace(/[-_\s]/g,'') === s);
  const style = found ? found[1] : { bg:T.div, color:T.mu };
  return (
    <span style={{ fontSize:12, fontWeight:600, padding:'2px 7px', borderRadius:4,
      background:style.bg, color:style.color }}>
      {status||'—'}
    </span>
  );
}

/* Tag chips */
function Tags({ tags, clickable=false }) {
  if (!tags) return null;
  const arr = typeof tags === 'string' ? tags.split(',').map(t=>t.trim()).filter(Boolean)
    : Array.isArray(tags) ? tags : [];
  if (!arr.length) return null;
  return (
    <div style={{ display:'flex', flexWrap:'wrap', gap:3 }}>
      {arr.map((t,i) => (
        <span key={i} style={{ fontSize:11, fontWeight:600, padding:'2px 7px', borderRadius:10,
          background:T.purb, color:T.purtx, cursor:clickable?'pointer':'default' }}>
          {t}
        </span>
      ))}
    </div>
  );
}

/* Chart axes config */
const fAxis = v => {
  if (v == null || isNaN(+v)) return '';
  const n = +v;
  const a = Math.abs(n), s = n < 0 ? '-' : '';
  if (a >= 1e6) return s + '$' + (a/1e6).toFixed(1) + 'M';
  if (a >= 1e3) return s + '$' + (a/1e3).toFixed(0) + 'K';
  if (a > 0) return s + '$' + a.toFixed(0);
  return '$0';
};
const ax = {
  xProps: { tick:{ fontSize:12, fill:T.mu }, axisLine:false, tickLine:false },
  yProps: { tick:{ fontSize:12, fill:T.mu }, axisLine:false, tickLine:false, width:72 },
  grid:   { stroke:T.bdr, strokeDasharray:'3 3', vertical:false },
};

/* Custom chart tooltip */
function ChartTip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background:T.card, border:`1px solid ${T.bdr}`, borderRadius:8,
      padding:'9px 13px', fontSize:12.5, boxShadow:`0 2px 8px ${T.shadow}` }}>
      <div style={{ fontWeight:700, color:T.tx, marginBottom:6 }}>{label}</div>
      {payload.map((p,i) => (
        <div key={i} style={{ color:p.color, marginBottom:2 }}>
          {p.name}: {f$(p.value)}
        </div>
      ))}
    </div>
  );
}

/* Insight card */
function InsightCard({ title, body }) {
  return (
    <div style={{ background:T.prib, border:`1px solid #C3D5FF`, borderRadius:8,
      padding:'11px 14px', marginBottom:9 }}>
      <div style={{ fontSize:13, fontWeight:700, color:T.pritx, marginBottom:3 }}>{title}</div>
      <div style={{ fontSize:13, color:T.tx2, lineHeight:1.6 }}>{body}</div>
    </div>
  );
}

/* ── DATE FILTER HEADER ───────────────────────────────── */
/*
  Feedback: remove dropdown preset, use button groups instead.
  Design matches the web report style with preset buttons + date pickers.
*/
function DateFilter({ latestDate, dates, onChange, compare, onCompare, websites, websiteId, onWebsite }) {
  const [showCustom, setShowCustom] = useState(false);
  const [customS, setCustomS] = useState('');
  const [customE, setCustomE] = useState('');

  const base = latestDate || new Date().toISOString().slice(0,10);
  const offDate = (n) => { const d=new Date(base+'T12:00:00'); d.setDate(d.getDate()+n); return d.toISOString().slice(0,10); };

  const PRESETS = [
    { label:'Today',     start: base,         end: base },
    { label:'Yesterday', start: offDate(-1),   end: offDate(-1) },
    { label:'Last 7d',   start: offDate(-6),   end: base },
    { label:'Last 14d',  start: offDate(-13),  end: base },
    { label:'Last 30d',  start: offDate(-29),  end: base },
    { label:'This month',start: (() => { const d=new Date(base+'T12:00:00'); return new Date(d.getFullYear(),d.getMonth(),1).toISOString().slice(0,10); })(), end: base },
    { label:'Last month',start: (() => { const d=new Date(base+'T12:00:00'); return new Date(d.getFullYear(),d.getMonth()-1,1).toISOString().slice(0,10); })(),
                         end: (() => { const d=new Date(base+'T12:00:00'); return new Date(d.getFullYear(),d.getMonth(),0).toISOString().slice(0,10); })() },
    { label:'Custom',    custom: true },
  ];

  const COMPARE_OPTS = [
    { value:'none',        label:'No comparison' },
    { value:'prev_period', label:'vs Previous period (same length)' },
    { value:'prev_month',  label:'vs Previous month' },
    { value:'prev_year',   label:'vs Same period last year' },
  ];

  const active = PRESETS.find(p => !p.custom && p.start===dates.start && p.end===dates.end);

  return (
    <div style={{ background:T.card, borderBottom:`1px solid ${T.bdr}`, padding:'10px 20px',
      display:'flex', alignItems:'center', gap:8, flexWrap:'wrap', flexShrink:0 }}>

      {/* Preset buttons */}
      <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
        {PRESETS.map(p => (
          p.custom ? (
            <button key="custom" onClick={() => { setShowCustom(v=>!v); }}
              style={{ ...S.btnO, padding:'5px 11px', fontSize:12,
                ...(showCustom ? { background:T.prib, color:T.pri, borderColor:T.pri } : {}) }}>
              Custom
            </button>
          ) : (
            <button key={p.label} onClick={() => { onChange({ start:p.start, end:p.end }); setShowCustom(false); }}
              style={{ ...S.btnO, padding:'5px 11px', fontSize:12,
                ...(active?.label===p.label ? { background:T.prib, color:T.pri, borderColor:T.pri, fontWeight:600 } : {}) }}>
              {p.label}
            </button>
          )
        ))}
      </div>

      {/* Custom date pickers */}
      {showCustom && (
        <div style={{ display:'flex', gap:6, alignItems:'center' }}>
          <input type="date" value={customS} onChange={e=>setCustomS(e.target.value)} style={{ ...S.inp, fontSize:12 }}/>
          <span style={{ color:T.mu, fontSize:12 }}>to</span>
          <input type="date" value={customE} onChange={e=>setCustomE(e.target.value)} style={{ ...S.inp, fontSize:12 }}/>
          <button onClick={() => { if(customS&&customE) { onChange({start:customS,end:customE}); setShowCustom(false); } }}
            style={{ ...S.btn, padding:'5px 11px', fontSize:12 }}>Apply</button>
        </div>
      )}

      {/* Current range display */}
      {dates.start && (
        <span style={{ fontSize:12, color:T.mu, marginLeft:4 }}>
          {fDateShort(dates.start)} – {fDateShort(dates.end)}
        </span>
      )}

      <div style={{ marginLeft:'auto', display:'flex', gap:8, alignItems:'center' }}>
        {/* Website filter + Compare on same row, vertically centered */}
        {websites && websites.length > 0 && (
          <select name="website_id" value={websiteId||'all'} onChange={e=>onWebsite(e.target.value)} style={{ ...S.sel, fontSize:12, height:32 }}>
            <option value="all">All Sites</option>
            {websites.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        )}
        <select name="compare" value={compare||'none'} onChange={e=>onCompare(e.target.value)} style={{ ...S.sel, fontSize:12, height:32 }}>
          {COMPARE_OPTS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>
    </div>
  );
}

/* ── PAGE: EXECUTIVE OVERVIEW ─────────────────────────── */
function ExecPage({ dates, compare, websiteId, websites }) {
  const [kpis,     setKpis]     = useState(null);
  const [trend,    setTrend]    = useState([]);
  const [sites,    setSites]    = useState([]);
  const [topProds, setTopProds] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [err,      setErr]      = useState(null);
  const [trendMetrics, setTrendMetrics] = useState(['revenue','net_profit','ad_spend']);
  const [imgPreview, setImgPreview] = useState(null);

  useEffect(() => {
    setLoading(true); setErr(null);
    const q = { start:dates.start, end:dates.end, website_id:websiteId, compare };
    Promise.all([
      api('/exec/kpis',         q),
      api('/exec/trend',        { start:dates.start, end:dates.end, website_id:websiteId }),
      api('/exec/websites',     { start:dates.start, end:dates.end }),
      api('/exec/top-products', { start:dates.start, end:dates.end, website_id:websiteId }),
    ]).then(([k,tr,s,tp]) => {
      setKpis(k);
      setTrend(tr.map(r => ({ ...r, date:fDateShort(r.date) })));
      setSites(s);
      setTopProds(tp);
    }).catch(e => setErr(e.message)).finally(() => setLoading(false));
  }, [dates.start, dates.end, compare, websiteId]);

  if (loading) return <Spinner/>;
  const k = kpis || {};
  const cl = k.compare_label;
  // image preview for exec page

  const TREND_OPTS = [
    { key:'revenue',    label:'Revenue',    color:T.charts[0] },
    { key:'net_profit', label:'Net Profit', color:T.charts[1] },
    { key:'ad_spend',   label:'Ad Spend',   color:T.charts[2] },
    { key:'cogs',       label:'COGS',       color:T.charts[3] },
    { key:'orders',     label:'Orders',     color:T.charts[4] },
  ];

  const recs = [];
  if (k.roas >= 4) recs.push({ title:'Strong ROAS — Consider Scaling', body:`Blended ROAS of ${fX(k.roas)} is healthy. Consider a 10-15% budget increase on best-performing campaigns before the Q2 July 4th peak.` });
  else if (k.roas >= 2) recs.push({ title:'ROAS Below Target', body:`Blended ROAS of ${fX(k.roas)} is below the 4x target. Identify top 20% campaigns by ROAS and reallocate budget from underperformers.` });
  else recs.push({ title:'Low ROAS Alert', body:`Blended ROAS of ${fX(k.roas)} is below 2x breakeven. Pause underperforming campaigns immediately and audit creative fatigue on Facebook.` });

  if (k.margin > 15) recs.push({ title:'Healthy Margin — Protect It', body:`Net margin of ${fP(k.margin)} is strong. Watch for COGS increases from supplier pricing changes heading into peak season.` });
  else if (k.margin > 8) recs.push({ title:'Margin Improvement Opportunity', body:`Net margin of ${fP(k.margin)} is acceptable but below 15% target. Test a 5-8% price increase on top SKUs — flag products tend to have low price sensitivity.` });
  else recs.push({ title:'Thin Margins — Action Required', body:`Net margin of ${fP(k.margin)} is critically low. Top levers: (1) negotiate COGS reduction with suppliers, (2) cut spend on campaigns with ROAS < 2x, (3) review payment fee rates.` });

  if (k.refund_rate > 3) recs.push({ title:'Elevated Refund Rate', body:`Refund rate of ${fP(k.refund_rate)} exceeds 3% threshold. Check Refunds page for top reasons — damaged in shipping and wrong item received are the most common fixable causes.` });
  else recs.push({ title:'Refund Rate Under Control', body:`Refund rate of ${fP(k.refund_rate)} is healthy. Continue monitoring product description accuracy and packaging quality.` });

  if (k.aov < 50) recs.push({ title:'AOV Below $50 — Bundle Opportunity', body:`Current AOV of ${f$2(k.aov)} has room to grow. Test a "Buy 2 Get 10% Off" bundle on 250th Anniversary SKUs, or raise free shipping threshold to $65 to incentivize larger orders.` });
  else recs.push({ title:'Maintain AOV Momentum', body:`AOV of ${f$2(k.aov)} is solid. Consider upsell prompts at cart (e.g. matching garden flag with grommet flag purchase) to push past $85 AOV.` });

  if (k.ad_spend > 0 && k.fb_spend/k.ad_spend > 0.75) recs.push({ title:'Ad Channel Concentration Risk', body:`Facebook accounts for ${fP(k.fb_spend/k.ad_spend*100)} of total ad spend. Consider diversifying into Google Shopping and Bing to reduce dependency on a single channel.` });

  return (
    <div>
      <ImageModal src={imgPreview} onClose={()=>setImgPreview(null)}/>
      <Err msg={err}/>
      <KpiGrid>
        <KpiCard label="Total Revenue" value={f$2(+(k.sale_display||k.revenue||0))} delta={k.delta_revenue} compareLabel={cl}
          tooltip="Total sales revenue minus tip for the selected period"/>
        <KpiCard label="Total Orders"  value={fN(k.orders)} delta={k.delta_orders} compareLabel={cl}
          tooltip="Number of orders placed in the selected period"/>
        <KpiCard label="AOV"           value={f$2(+(k.aov||0))} delta={k.delta_aov} compareLabel={cl}
          tooltip="Average Order Value = (Revenue - Tips) / Total Orders"/>
        <KpiCard label="Ad Spend"      value={f$2(+(k.ad_spend||0))} delta={k.delta_ad_spend} compareLabel={cl}
          color={T.ora} tooltip="Total spend across Facebook, Google, Bing, Email ads"/>
      </KpiGrid>
      <KpiGrid>
        <KpiCard label="Blended ROAS"  value={fX(+(k.roas||0))} delta={k.delta_roas} compareLabel={cl}
          color={(+k.roas)>=4?T.grn:(+k.roas)>=2?T.ora:T.red}
          sub={(+k.roas)>=4?'Healthy':'Below target'}
          tooltip="Return on Ad Spend = (Revenue - Tips) / Total Ad Spend"/>
        <KpiCard label="Gross Profit"  value={f$2(+(k.gross_profit||0))} delta={k.delta_gross_profit} compareLabel={cl}
          color={(+k.gross_profit)>0?T.grn:T.red}
          tooltip="Revenue (excl. tips) minus COGS"/>
        <KpiCard label="Net Profit"    value={f$2(+(k.net_profit||0))} delta={k.delta_net_profit} compareLabel={cl}
          color={(+k.net_profit)>0?T.grn:T.red}
          tooltip="Revenue - COGS - Tax - Payment Fee - Ad Spend - Refunds"/>
        <KpiCard label="Net Margin"    value={fP(+(k.margin||0))} delta={k.delta_margin} compareLabel={cl}
          color={(+k.margin)>15?T.grn:(+k.margin)>8?T.ora:T.red}
          sub={`Refund rate: ${fP(+(k.refund_rate||0))}`}
          tooltip="Net Profit / (Revenue - Tips) × 100"/>
      </KpiGrid>

      {/* Trend chart with metric selector */}
      <Card>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 }}>
          <div style={{ fontSize:14, fontWeight:700, color:T.tx }}>Revenue Trend — Daily</div>
          <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
            {TREND_OPTS.map(o => (
              <button key={o.key}
                onClick={() => setTrendMetrics(v => v.includes(o.key) ? v.filter(x=>x!==o.key) : [...v,o.key])}
                style={{ padding:'4px 10px', border:`1px solid ${trendMetrics.includes(o.key)?o.color:T.bdr}`,
                  borderRadius:5, background:trendMetrics.includes(o.key)?o.color+'22':T.card,
                  color:trendMetrics.includes(o.key)?o.color:T.mu, fontSize:11.5, cursor:'pointer', fontFamily:'inherit' }}>
                {o.label}
              </button>
            ))}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={trend}>
            <CartesianGrid {...ax.grid}/>
            <XAxis dataKey="date" {...ax.xProps} tickCount={8}/>
            <YAxis {...ax.yProps} tickFormatter={fAxis}/>
            <Tooltip content={<ChartTip/>}/>
            {/* Revenue + Net Profit = Bars; ad_spend/cogs = Lines; orders = right axis */}
            {trendMetrics.includes('revenue') && (
              <Bar dataKey="revenue" name="Revenue" fill={T.charts[0]+'cc'} radius={[3,3,0,0]}/>
            )}
            {trendMetrics.includes('net_profit') && (
              <Bar dataKey="net_profit" name="Net Profit" fill={T.charts[1]+'cc'} radius={[3,3,0,0]}/>
            )}
            {trendMetrics.includes('ad_spend') && (
              <Line type="monotone" dataKey="ad_spend" name="Ad Spend" stroke={T.charts[2]} dot={false} strokeWidth={2}/>
            )}
            {trendMetrics.includes('cogs') && (
              <Line type="monotone" dataKey="cogs" name="COGS" stroke={T.charts[3]} dot={false} strokeWidth={2}/>
            )}
            {trendMetrics.includes('orders') && <>
              <Line type="monotone" dataKey="orders" name="Orders" stroke={T.charts[4]} dot={false} strokeWidth={2} yAxisId="r"/>
              <YAxis yAxisId="r" orientation="right" {...ax.yProps} tickFormatter={fN}/>
            </>}
          </ComposedChart>
        </ResponsiveContainer>
      </Card>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1.3fr', gap:12, marginBottom:12 }}>
        {/* P&L Summary */}
        <TableWrap style={{ margin:0 }}>
          <div style={{ padding:'10px 14px', borderBottom:`1px solid ${T.bdr}` }}>
            <span style={{ fontSize:14, fontWeight:700, color:T.tx }}>P&L Summary</span>
            <span style={{ fontSize:12, color:T.mu, marginLeft:10 }}>{dates.start} – {dates.end}</span>
          </div>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
            <tbody>
              {[
                { label:'Gross Revenue',   v:k.revenue,      pct:100,                                            bold:false },
                { label:'Tips',            v:-(k.tip||0),    pct:k.revenue>0?(k.tip||0)/k.revenue*100:0,         neg:true },
                { label:'Revenue (ex tip)',v:k.sale_display, pct:100,                                            bold:true },
                { label:'COGS',            v:-k.cogs,        pct:k.revenue>0?k.cogs/k.revenue*100:0,             neg:true },
                { label:'Gross Profit',    v:k.gross_profit, pct:k.revenue>0?k.gross_profit/k.revenue*100:0,     bold:true },
                { label:'Facebook Ads',    v:-k.fb_spend,    pct:k.revenue>0?k.fb_spend/k.revenue*100:0,         neg:true },
                { label:'Google Ads',      v:-k.ga_cost,     pct:k.revenue>0?k.ga_cost/k.revenue*100:0,          neg:true },
                { label:'Bing Ads',        v:-k.bing_spend,  pct:k.revenue>0?(k.bing_spend||0)/k.revenue*100:0,  neg:true },
                { label:'Email Ads',       v:-k.email_spend, pct:k.revenue>0?(k.email_spend||0)/k.revenue*100:0, neg:true },
                { label:'Shipping',        v:-k.shipping,    pct:k.revenue>0?k.shipping/k.revenue*100:0,         neg:true },
                { label:'Total Tax',       v:-k.total_tax,   pct:k.revenue>0?k.total_tax/k.revenue*100:0,        neg:true },
                { label:'Payment Fees',    v:-k.payment_fee, pct:k.revenue>0?k.payment_fee/k.revenue*100:0,      neg:true },
                { label:'Refunds',         v:-k.refunds,     pct:k.revenue>0?k.refunds/k.revenue*100:0,          neg:true },
                { label:'Net Profit',      v:k.net_profit,   pct:k.margin,                                       bold:true, big:true },
              ].map((r,i) => (
                <tr key={i} style={{ background:i%2===0?'':T.div+'44' }}>
                  <td style={{ padding:'7px 14px', fontSize:r.big?14:13, fontWeight:r.bold?700:400, color:T.tx }}>{r.label}</td>
                  <td style={{ padding:'7px 14px', textAlign:'right', fontVariantNumeric:'tabular-nums', fontSize:r.big?14:13, fontWeight:r.bold?700:400, color:r.neg?T.red:r.v>0?T.grn:T.tx }}>
                    {f$2(r.v)}
                  </td>
                  <td style={{ padding:'7px 14px', textAlign:'right' }}>
                    <span style={{ fontSize:11, fontWeight:600, padding:'2px 5px', borderRadius:3,
                      background:r.neg?T.redb:T.grnb, color:r.neg?T.redtx:T.grntx }}>
                      {fP(Math.abs(r.pct))}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>

        <div style={{ display:'flex', flexDirection:'column', gap:12, minHeight:0 }}>
          <Card style={{ margin:0 }}>
            <CardTitle>Revenue by store</CardTitle>
            <ResponsiveContainer width="100%" height={Math.max(130, sites.length * 32)}>
              <BarChart data={sites} layout="vertical" margin={{ left:8, right:16 }}>
                <XAxis type="number" {...ax.xProps} tickFormatter={f$}/>
                <YAxis type="category" dataKey="website" {...ax.yProps} width={100} tick={{ fontSize:12, fill:T.mu }}/>
                <Tooltip content={<ChartTip/>}/>
                <Bar dataKey="revenue" name="Revenue" fill={T.pri} radius={[0,4,4,0]}/>
              </BarChart>
            </ResponsiveContainer>
          </Card>

          <Card style={{ margin:0, flex:1 }}>
            <CardTitle>Ad channel mix</CardTitle>
            <ResponsiveContainer width="100%" height={190}>
              <PieChart margin={{ top:0, right:0, bottom:0, left:0 }}>
                <Pie data={[
                  { name:'Facebook', value:k.fb_spend||0 },
                  { name:'Google',   value:k.ga_cost||0 },
                  { name:'Email',    value:k.email_spend||0 },
                  { name:'Bing',     value:k.bing_spend||0 },
                ]} cx="62%" cy="50%" innerRadius={46} outerRadius={72} dataKey="value">
                  {T.charts.map((cc,i) => <Cell key={i} fill={cc}/>)}
                </Pie>
                <Tooltip formatter={f$}/>
                <Legend
                  iconSize={11}
                  layout="vertical"
                  align="left"
                  verticalAlign="middle"
                  wrapperStyle={{ fontSize:13, paddingLeft:4, paddingRight:4 }}
                  formatter={(value, entry) => (
                    <span style={{ color:T.tx2, fontSize:13, marginLeft:2 }}>
                      {value}: {f$(entry?.payload?.value||0)}
                    </span>
                  )}
                />
              </PieChart>
            </ResponsiveContainer>
          </Card>
        </div>
      </div>

      {/* Top products */}
      <TableWrap>
        <div style={{ padding:'10px 14px', borderBottom:`1px solid ${T.bdr}` }}>
          <span style={{ fontSize:15, fontWeight:700, color:T.tx }}>Top Products</span>
        </div>
        <div style={{ overflowX:'auto', maxHeight:380, overflowY:'auto' }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
            <thead><tr>
              <th style={S.th}>Image</th>
              <th style={S.th}>Product</th>
              <th style={{ ...S.th, textAlign:'right' }}>Revenue</th>
              <th style={{ ...S.th, textAlign:'right' }}>Orders</th>
              <th style={{ ...S.th, textAlign:'right' }}>Units</th>
            </tr></thead>
            <tbody>
              {topProds.map((r,i) => (
                <tr key={i} onMouseEnter={e=>e.currentTarget.style.background=T.div} onMouseLeave={e=>e.currentTarget.style.background=''}>
                  <td style={{ ...S.td, width:36, cursor:r.image?'zoom-in':'default' }}
                    onClick={()=>r.image&&setImgPreview(r.image)}>
                    {r.image
                      ? <img src={r.image} style={{ width:34,height:34,borderRadius:5,objectFit:'cover',border:`1px solid ${T.bdr}` }} onError={e=>e.target.style.display='none'} alt=""/>
                      : <div style={{ width:40,height:40,borderRadius:6,background:T.div,display:'flex',alignItems:'center',justifyContent:'center',fontSize:10,color:T.mu }}>IMG</div>}
                  </td>
                  <td style={{ ...S.td, maxWidth:160, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}><span style={{ fontWeight:600, color:T.tx, fontSize:14 }}>{r.name}</span></td>
                  <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:700, fontSize:15 }}>{f$2(r.revenue)}</td>
                  <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontSize:14 }}>{fN(r.orders)}</td>
                  <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontSize:14 }}>{fN(r.units)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </TableWrap>

      <div style={{ marginTop:16 }}>
        <div style={{ fontSize:16, fontWeight:700, color:T.tx, marginBottom:10, display:'flex', alignItems:'center', gap:8 }}>
          <span style={{ width:4, height:20, background:T.pri, borderRadius:2, display:'inline-block' }}/>
          Alerts & Recommendations
        </div>
        {recs.map((r,i) => <InsightCard key={i} {...r}/>)}
      </div>
    </div>
  );
}

/* ── PAGE: DAILY PERFORMANCE ──────────────────────────── */
function DailyPage({ latestDate, websiteId, dates }) {
  const [rows,    setRows]    = useState([]);
  const [prods,   setProds]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [err,     setErr]     = useState(null);
  const [expanded, setExpanded] = useState({});  // per-card expanded state
  const [prodPage, setProdPage] = useState(1);
  const [prodTotal, setProdTotal] = useState(0);
  const [prodPages, setProdPages] = useState(1);
  const [prodSearch, setProdSearch] = useState('');
  const [prodLoading, setProdLoading] = useState(false);
  const [prodKey, setProdKey] = useState(0);
  const DP_ALL_COLS = [
    { key:'image',               label:'Image' },
    { key:'parent_name',         label:'Parent Name' },
    { key:'parent_sku',          label:'Parent SKU' },
    { key:'product_code',        label:'Product Code' },
    { key:'product_type',        label:'Product Type' },
    { key:'total_orders',        label:'Orders' },
    { key:'product_quantity',    label:'Quantity' },
    { key:'sub_total',           label:'Subtotal' },
    { key:'total_taxes',         label:'Taxes' },
    { key:'discount',            label:'Discount' },
    { key:'total_cogs',          label:'Cogs' },
    { key:'google_ads_cost',     label:'GG Ads Cost' },
    { key:'google_ads_revenue',  label:'GG Ads Revenue' },
    { key:'platform',            label:'Platform' },
    { key:'website_name',        label:'Website' },
    { key:'tags',                label:'Tags' },
    { key:'date_created',        label:'Date Created' },
  ];
  const DP_DEFAULT = ['image','parent_name','parent_sku','product_code','product_type','total_orders','product_quantity','sub_total','total_cogs','google_ads_cost','google_ads_revenue','platform','website_name','tags'];
  const [dpVis, setDpVis] = useState(DP_DEFAULT);

  // Daily filter state (separate from global filter)
  const base = latestDate || new Date().toISOString().slice(0,10);
  const offDate = n => { const d=new Date(base+'T12:00:00'); d.setDate(d.getDate()+n); return d.toISOString().slice(0,10); };

  const [preset,  setPreset]  = useState('daily4');
  const [compare, setCompare] = useState('none');
  const [showCustom, setShowCustom] = useState(false);
  const [customS, setCustomS] = useState('');
  const [customE, setCustomE] = useState('');

  const PRESET_OPTS = [
    { value:'daily4',  label:'Today / Yesterday / 2d / 3d' },
    { value:'daily7',  label:'Today / Yesterday / 7d / 14d' },
    { value:'week',    label:'This week / Last week / 2w / 3w' },
    { value:'month',   label:'This month / Last month / 2mo / 3mo' },
    { value:'quarter', label:'This quarter / Last quarter' },
    { value:'custom',  label:'Custom range' },
  ];
  const COMPARE_OPTS = [
    { value:'none',       label:"Don't compare" },
    { value:'prev_week',  label:'Previous week' },
    { value:'prev_month', label:'Previous month' },
    { value:'prev_3m',    label:'Previous 3 months' },
    { value:'prev_6m',    label:'Previous 6 months' },
    { value:'prev_year',  label:'Previous year' },
  ];

  // Build date offsets for each column
  const offsets = {
    daily4:  [0, -1, -2, -3],
    daily7:  [0, -1, -7, -14],
    week:    [0, -7, -14, -21],
    month:   [0, -30, -60, -90],
    quarter: [0, -91],
  }[preset] || [0,-1,-2,-3];

  const CARD_LABELS = { 0:'Today', '-1':'Yesterday', '-2':'2 days ago', '-3':'3 days ago',
    '-7':'7 days ago', '-14':'14 days ago', '-21':'21 days ago', '-30':'30 days ago',
    '-60':'60 days ago', '-90':'90 days ago', '-91':'Last quarter' };
  const CARD_COLORS = [T.pri, T.grn, T.pur, T.ora];

  const METRICS = [
    { key:'net_profit',  label:'Profit',    fmt:f$2 },
    { key:'sales',       label:'Margin',    fmt:(v,row) => row.sales>0 ? fP(row.net_profit/row.sales*100) : '—', valKey:'net_profit' },
    { key:'sales',       label:'Sales',     fmt:f$ },
    { key:'cogs',        label:'Cogs',      fmt:f$ },
    { key:'ads',         label:'Ads',       fmt:f$ },
    { key:'aov',         label:'AOV',       fmt:f$2 },
    { key:'roas',        label:'ROAS',      fmt:fX },
    { key:'orders',      label:'Orders',    fmt:fN },
    { key:'units',       label:'Units',     fmt:fN },
    { key:'refunds',     label:'Refunds',   fmt:f$ },
    { key:'shipping',    label:'Shipping',  fmt:f$ },
    { key:'tax',         label:'Tax',       fmt:f$ },
    { key:'payment_fee', label:'Pay Fee',   fmt:f$ },
    { key:'discounts',   label:'Discount',  fmt:f$ },
    { key:'tip',         label:'Tip',       fmt:f$ },
  ];
  const SHOW_INIT = 7;

  const fetchDate = (off) => {
    if (preset === 'custom' && customS && customE) {
      if (off === 0) return customS;
      return null;
    }
    return offDate(off);
  };

  useEffect(() => {
    if (!latestDate) { setLoading(false); return; }
    setLoading(true);
    const allDates = [...new Set(offsets.map(o => fetchDate(o)).filter(Boolean))];
    if (!allDates.length) { setLoading(false); return; }
    const minD = allDates.reduce((a,b) => a<b?a:b);
    const maxD = allDates.reduce((a,b) => a>b?a:b);

    api('/daily/periods', { start:minD, end:maxD, website_id:websiteId })
      .then(data => {
        const byDate = {};
        // Normalize date key — MySQL may return Date obj, datetime string, or date string
        data.forEach(r => {
          let key;
          if (r.date instanceof Date) {
            key = r.date.toISOString().slice(0,10);
          } else if (typeof r.date === 'string') {
            // Handle both 'YYYY-MM-DD' and 'YYYY-MM-DD HH:MM:SS'
            key = r.date.slice(0,10);
          } else {
            key = String(r.date).slice(0,10);
          }
          byDate[key] = r;
        });
        const built = offsets.map(off => {
          const dt = fetchDate(off);
          if (!dt) return null;
          const cur  = byDate[dt] || {};
          const prevOff = off - (preset==='daily4'||preset==='daily7'?1:preset==='week'?7:preset==='month'?30:91);
          const prevDt = compare!=='none' ? fetchDate(prevOff) : null;
          const prev = prevDt ? byDate[prevDt] : null;
          return { label: CARD_LABELS[String(off)] || `${Math.abs(off)}d ago`, dt, prev, ...cur };
        }).filter(Boolean);
        setRows(built);
      }).catch(e => setErr(e.message)).finally(() => setLoading(false));
  }, [latestDate, websiteId, preset, compare, customS, customE]);

  // Compute the date range for product table from DailyPage's own date system
  const prodStart = preset === 'custom' && customS ? customS : offDate(Math.min(...offsets));
  const prodEnd   = preset === 'custom' && customE ? customE : base;

  useEffect(() => {
    if (!prodStart || !prodEnd) return;
    setProdKey(k => k+1);
    setProdLoading(true);
    setProds([]);
    setProdTotal(0);
    api('/daily/products', { start:prodStart, end:prodEnd, website_id:websiteId, page:prodPage, search:prodSearch })
      .then(d => {
        if (d?.rows) { setProds(d.rows); setProdTotal(d.total||0); setProdPages(d.pages||1); }
        else { setProds(d||[]); setProdTotal((d||[]).length); setProdPages(1); }
      }).catch(()=>{ setProds([]); setProdTotal(0); setProdPages(1); })
      .finally(()=>setProdLoading(false));
  }, [prodStart, prodEnd, websiteId, prodPage, prodSearch]);

  return (
    <div>
      {/* Filter bar */}
      <div style={{ background:T.card, border:`1px solid ${T.bdr}`, borderRadius:10, padding:'12px 16px', marginBottom:14 }}>
        <div style={{ display:'flex', gap:8, flexWrap:'wrap', alignItems:'center', marginBottom:8 }}>
          <span style={{ fontSize:13, color:T.mu, fontWeight:600 }}>Period:</span>
          {PRESET_OPTS.map(o => (
            <button key={o.value} onClick={() => { setPreset(o.value); if(o.value!=='custom') setShowCustom(false); else setShowCustom(true); }}
              style={{ ...S.btnO, padding:'5px 11px', fontSize:12,
                ...(preset===o.value?{ background:T.prib, color:T.pri, borderColor:T.pri, fontWeight:600 }:{}) }}>
              {o.label}
            </button>
          ))}
        </div>
        <div style={{ display:'flex', gap:8, flexWrap:'wrap', alignItems:'center' }}>
          <span style={{ fontSize:13, color:T.mu, fontWeight:600 }}>Compare:</span>
          {COMPARE_OPTS.map(o => (
            <button key={o.value} onClick={() => setCompare(o.value)}
              style={{ ...S.btnO, padding:'5px 11px', fontSize:12,
                ...(compare===o.value?{ background:T.prib, color:T.pri, borderColor:T.pri, fontWeight:600 }:{}) }}>
              {o.label}
            </button>
          ))}
        </div>
        {showCustom && (
          <div style={{ display:'flex', gap:8, alignItems:'center', marginTop:10 }}>
            <input type="date" value={customS} onChange={e=>setCustomS(e.target.value)} style={{ ...S.inp, fontSize:12 }}/>
            <span style={{ color:T.mu }}>to</span>
            <input type="date" value={customE} onChange={e=>setCustomE(e.target.value)} style={{ ...S.inp, fontSize:12 }}/>
            <button onClick={()=>setShowCustom(false)} style={{ ...S.btn, padding:'5px 11px', fontSize:12 }}>Apply</button>
          </div>
        )}
      </div>

      <Err msg={err}/>
      {loading ? <Spinner/> : (
        <div style={{ display:'grid', gridTemplateColumns:`repeat(${rows.length},1fr)`, gap:10, marginBottom:16 }}>
          {rows.map((d, idx) => {
            const isExp = expanded[idx];
            const metrics = isExp ? METRICS : METRICS.slice(0, SHOW_INIT);
            return (
              <div key={idx} style={{ ...S.card, overflow:'hidden' }}>
                <div style={{ background:CARD_COLORS[idx]||T.pri, padding:'11px 14px', color:'#fff' }}>
                  <div style={{ fontWeight:700, fontSize:14 }}>{d.label}</div>
                  <div style={{ fontSize:11.5, opacity:.85, marginTop:2 }}>{fDate(d.dt)}</div>
                </div>
                <div style={{ padding:'10px 13px' }}>
                  {metrics.map((m, mi) => {
                    const cv = m.fmt ? m.fmt(d[m.key]||0, d) : d[m.key]||0;
                    const pv = d.prev && m.fmt ? m.fmt(d.prev[m.key]||0, d.prev) : null;
                    const cvRaw = d[m.key]||0;
                    const pvRaw = d.prev ? d.prev[m.key]||0 : null;
                    const dv = pvRaw != null && Math.abs(pvRaw) > 0 ? (cvRaw - pvRaw)/Math.abs(pvRaw)*100 : null;
                    return (
                      <div key={mi} style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:8, minHeight:38 }}>
                        <div>
                          <div style={{ fontSize:12, color:T.mu, display:'flex', alignItems:'center', gap:5 }}>
                            {m.label}
                            {dv != null && <DeltaBadge v={dv}/>}
                          </div>
                          <div style={{ fontSize:15, fontWeight:700, color:T.tx, fontVariantNumeric:'tabular-nums', marginTop:1 }}>
                            {cv}
                          </div>
                        </div>
                        {pv != null && compare !== 'none' && (
                          <div style={{ fontSize:12, color:T.mu, fontVariantNumeric:'tabular-nums', textAlign:'right' }}>{pv}</div>
                        )}
                      </div>
                    );
                  })}
                  <button onClick={() => setExpanded(v => ({ ...v, [idx]: !isExp }))}
                    style={{ width:'100%', background:'none', border:'none', color:T.pri, fontSize:12.5,
                      cursor:'pointer', marginTop:4, textAlign:'center', padding:'4px 0' }}>
                    {isExp ? 'Show less ↑' : 'Show more ↓'}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Product Detail Table */}
      <div style={{ fontSize:14, fontWeight:700, color:T.tx, marginBottom:10 }}>
        Product Report Detail — {fDate(prodStart)} to {fDate(prodEnd)}
      </div>
      <TableWrap>
        <SearchBar>
          <input placeholder="Search product..." value={prodSearch}
            onChange={e=>{ setProdSearch(e.target.value); setProdPage(1); }}
            style={{ ...S.inp, width:200 }}/>
          <span style={{ fontSize:13, color:T.mu }}>{prodTotal.toLocaleString()} items</span>
          <ColChooser allCols={DP_ALL_COLS} visible={dpVis} onChange={(k,v) => k==='__reset__' ? setDpVis(DP_DEFAULT) : setDpVis(cv => v ? [...cv,k] : cv.filter(x=>x!==k))}/>
        </SearchBar>
        <div key={prodKey}>
        {prodLoading ? (
          <div style={{ padding:60, textAlign:'center' }}><Spinner/></div>
        ) : (
        <div style={{ overflowX:'auto', maxHeight:480, overflowY:'auto' }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
            <thead><tr>
              <th style={S.th}></th>
              {dpVis.includes('image')              && <th style={{ ...S.th, width:46 }}>Image</th>}
              {dpVis.includes('parent_name')        && <th style={{ ...S.th, minWidth:320 }}>Parent Name</th>}
              {dpVis.includes('parent_sku')         && <th style={{ ...S.th, minWidth:250 }}>Parent SKU</th>}
              {dpVis.includes('product_code')       && <th style={{ ...S.th, minWidth:140 }}>Product Code</th>}
              {dpVis.includes('product_type')       && <th style={S.th}>Product Type</th>}
              {dpVis.includes('total_orders')       && <th style={{ ...S.th, textAlign:'right' }}>Orders</th>}
              {dpVis.includes('product_quantity')   && <th style={{ ...S.th, textAlign:'right' }}>Qty</th>}
              {dpVis.includes('sub_total')          && <th style={{ ...S.th, textAlign:'right' }}>Subtotal</th>}
              {dpVis.includes('total_taxes')        && <th style={{ ...S.th, textAlign:'right' }}>Taxes</th>}
              {dpVis.includes('discount')           && <th style={{ ...S.th, textAlign:'right' }}>Discount</th>}
              {dpVis.includes('total_cogs')         && <th style={{ ...S.th, textAlign:'right' }}>Cogs</th>}
              {dpVis.includes('google_ads_cost')    && <th style={{ ...S.th, textAlign:'right' }}>GG Ads Cost</th>}
              {dpVis.includes('google_ads_revenue') && <th style={{ ...S.th, textAlign:'right' }}>GG Ads Rev</th>}
              {dpVis.includes('platform')           && <th style={S.th}>Platform</th>}
              {dpVis.includes('website_name')       && <th style={{ ...S.th, minWidth:120 }}>Website</th>}
              {dpVis.includes('tags')               && <th style={{ ...S.th, minWidth:280 }}>Tags</th>}
              {dpVis.includes('date_created')       && <th style={S.th}>Date Created</th>}
            </tr></thead>
            <tbody>
              {prods.map((p,i) => (
                <tr key={i} onMouseEnter={e=>e.currentTarget.style.background=T.div} onMouseLeave={e=>e.currentTarget.style.background=''}>
                  <td style={{ ...S.td, fontSize:15, fontWeight:700, color:T.pri, cursor:'pointer', textAlign:'center', width:32 }}>+</td>
                  {dpVis.includes('image') && <td style={{ ...S.td, width:46, padding:'6px 8px' }}>
                    {imgSrc(p.image)
                      ? <img src={imgSrc(p.image)} style={{ width:36,height:36,borderRadius:5,objectFit:'cover',border:`1px solid ${T.bdr}` }} onError={e=>{e.target.style.display='none';}} alt=""/>
                      : <div style={{ width:36,height:36,borderRadius:5,background:T.div,display:'flex',alignItems:'center',justifyContent:'center',fontSize:10,color:T.mu }}>—</div>}
                  </td>}
                  {dpVis.includes('parent_name')        && <td style={{ ...S.td, minWidth:200, whiteSpace:'normal', lineHeight:1.4, fontWeight:600, color:T.tx }}>{p.parent_name}</td>}
                  {dpVis.includes('parent_sku')         && <td style={{ ...S.td, minWidth:160, fontSize:14, color:T.mu, wordBreak:'break-all' }}>{p.parent_sku||'—'}</td>}
                  {dpVis.includes('product_code')       && <td style={{ ...S.td, minWidth:140, fontSize:14, color:T.mu, fontFamily:'monospace' }}>{p.product_code||'—'}</td>}
                  {dpVis.includes('product_type')       && <td style={S.td}>{p.product_type ? <StatusBadge status={p.product_type}/> : '—'}</td>}
                  {dpVis.includes('total_orders')       && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{fN(p.total_orders)}</td>}
                  {dpVis.includes('product_quantity')   && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{fN(p.product_quantity)}</td>}
                  {dpVis.includes('sub_total')          && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:600 }}>{f$2(p.sub_total)}</td>}
                  {dpVis.includes('total_taxes')        && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{f$2(p.total_taxes)}</td>}
                  {dpVis.includes('discount')           && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.ora }}>{f$2(p.discount)}</td>}
                  {dpVis.includes('total_cogs')         && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.red }}>{f$2(p.total_cogs)}</td>}
                  {dpVis.includes('google_ads_cost')    && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.ora }}>{f$2(p.google_ads_cost)}</td>}
                  {dpVis.includes('google_ads_revenue') && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.grn }}>{f$2(p.google_ads_revenue)}</td>}
                  {dpVis.includes('platform')           && <td style={{ ...S.td, fontSize:14 }}>{p.platform||'—'}</td>}
                  {dpVis.includes('website_name')       && <td style={{ ...S.td, minWidth:120, fontSize:14 }}>{p.website_name||'—'}</td>}
                  {dpVis.includes('tags')               && <td style={{ ...S.td, minWidth:280, whiteSpace:'normal' }}><Tags tags={p.tags} clickable/></td>}
                  {dpVis.includes('date_created')       && <td style={{ ...S.td, fontSize:14, color:T.mu, whiteSpace:'nowrap' }}>{fDate(p.date_created)}</td>}
                </tr>
              ))}
              {prods.length === 0 && (
                <tr><td colSpan={17} style={{ padding:40, textAlign:'center', color:T.mu, fontSize:13 }}>No data</td></tr>
              )}
            </tbody>
          </table>
        </div>
        )}
        </div>
        <Pager page={prodPage} pages={prodPages} total={prodTotal} per={50} onPage={p=>{ setProdPage(p); }}/>
      </TableWrap>
    </div>
  );
}

/* ── PAGE: ORDERS ─────────────────────────────────────── */
function OrdersPage({ dates, websiteId }) {
  const [rows,  setRows]  = useState([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [page,  setPage]  = useState(1);
  const [loading, setLoading] = useState(true);
  const [err,   setErr]   = useState(null);
  const [filters, setFilters] = useState({ status:'all', order:'', product:'', email:'', coupon:'' });
  const [expanded, setExpanded] = useState(null);
  const [expandedItems, setExpandedItems] = useState([]);
  const [kpi, setKpi] = useState({});
  const [kpiPrev, setKpiPrev] = useState({});
  const PER = 20;

  const ALL_COLS = [
    { key:'order_id',        label:'Order ID' },
    { key:'order_number',    label:'Order Number' },
    { key:'status',          label:'Status' },
    { key:'products',        label:'List Products' },
    { key:'tracking_code',   label:'Tracking Number' },
    { key:'landing_site',    label:'Landing Site' },
    { key:'first_name',      label:'Name' },
    { key:'email',           label:'Email' },
    { key:'state',           label:'State' },
    { key:'total_quantity',  label:'Quantity' },
    { key:'total',           label:'Total' },
    { key:'coupons',         label:'Coupons' },
    { key:'shipping_total',  label:'Shipping Total' },
    { key:'payment_fee',     label:'Payment Fee' },
    { key:'total_tax',       label:'Tax Total' },
    { key:'shipping_tax',    label:'Shipping Tax' },
    { key:'refund_total',    label:'Refunds' },
    { key:'payment_method_title', label:'Payment Method' },
    { key:'date_created',    label:'Created At' },
  ];
  const DEFAULT_VIS = ['order_id','order_number','status','products','tracking_code','landing_site','first_name','email','state','total_quantity','total','coupons','date_created'];
  const [vis, setVis] = useState(DEFAULT_VIS);

  const load = useCallback(() => {
    setLoading(true);
    api('/orders', {
      start: dates.start, end: dates.end, website_id: websiteId,
      status: filters.status, search_order: filters.order,
      search_email: filters.email, search_coupon: filters.coupon, page, per: PER,
    }).then(d => { setRows(d.rows||[]); setTotal(d.total||0); setPages(d.pages||1); })
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false));
    // Fetch KPIs for delta comparison
    if (dates.start && dates.end) {
      api('/exec/kpis', { start:dates.start, end:dates.end, website_id:websiteId }).then(setKpi).catch(()=>{});
      const ds=new Date(dates.start+'T12:00:00'), de=new Date(dates.end+'T12:00:00');
      const days=Math.round((de-ds)/86400000)+1;
      const pe=new Date(ds); pe.setDate(pe.getDate()-1);
      const ps=new Date(pe); ps.setDate(ps.getDate()-days+1);
      const fmt=d=>d.toISOString().slice(0,10);
      api('/exec/kpis', { start:fmt(ps), end:fmt(pe), website_id:websiteId }).then(setKpiPrev).catch(()=>{});
    }
  }, [dates.start, dates.end, websiteId, filters.status, filters.order, filters.email, filters.coupon, page]);

  useEffect(() => { load(); }, [load]);

  const expandOrder = async (row) => {
    if (expanded === row.id) { setExpanded(null); return; }
    setExpanded(row.id);
    const items = await api(`/orders/${row.id}/items`).catch(()=>[]);
    setExpandedItems(items);
  };

  const handleColChange = (key, checked) => {
    if (key==='__reset__') { setVis(DEFAULT_VIS); return; }
    setVis(v => checked ? [...v,key] : v.filter(k=>k!==key));
  };

  const totals = (Array.isArray(rows)?rows:[]).reduce((a,r) => ({
    count: a.count+1, total: a.total+(+r.total||0), refunds: a.refunds+(+r.refund_total||0)
  }), { count:0, total:0, refunds:0 });

  return (
    <div>
      <KpiGrid cols={4}>
        <KpiCard label="Total Orders" value={fN(total)}
          delta={kpiPrev.orders>0?(total-kpiPrev.orders)/kpiPrev.orders*100:null}
          tooltip="Total orders matching current filters"/>
        <KpiCard label="Total Revenue" value={f$2(kpi.revenue||0)} color={T.grn}
          delta={kpiPrev.revenue>0?(+(kpi.revenue||0)-kpiPrev.revenue)/kpiPrev.revenue*100:null}
          tooltip="Total revenue in selected period"/>
        <KpiCard label="Net Profit" value={f$2(kpi.net_profit||0)} color={(+(kpi.net_profit||0))>0?T.grn:T.red}
          delta={kpiPrev.net_profit&&Math.abs(kpiPrev.net_profit)>0?(+(kpi.net_profit||0)-kpiPrev.net_profit)/Math.abs(kpiPrev.net_profit)*100:null}
          tooltip="Revenue - COGS - Tax - Fees - Ads - Refunds"/>
        <KpiCard label="Blended ROAS" value={fX(kpi.roas||0)} color={(+(kpi.roas||0))>=4?T.grn:T.ora}
          delta={kpiPrev.roas>0?(+(kpi.roas||0)-kpiPrev.roas)/kpiPrev.roas*100:null}
          tooltip="Revenue / Ad Spend"/>
      </KpiGrid>

      <TableWrap>
        <SearchBar>
          <input placeholder="Order number..." value={filters.order}
            onChange={e => setFilters(f=>({...f,order:e.target.value}))}
            style={{ ...S.inp, width:150 }}/>
          <input placeholder="Search product..." value={filters.product}
            onChange={e => setFilters(f=>({...f,product:e.target.value}))}
            style={{ ...S.inp, width:150 }}/>
          <input placeholder="Email..." value={filters.email}
            onChange={e => setFilters(f=>({...f,email:e.target.value}))}
            style={{ ...S.inp, width:150 }}/>
          <input placeholder="Coupon..." value={filters.coupon}
            onChange={e => setFilters(f=>({...f,coupon:e.target.value}))}
            style={{ ...S.inp, width:130 }}/>
        </SearchBar>
        <SearchBar>
          <select name="filters" value={filters.status} onChange={e=>{ setFilters(f=>({...f,status:e.target.value})); setPage(1); }}
            style={S.sel}>
            <option value="all">All Status</option>
            <option value="paid">Paid</option>
            <option value="refunded">Refunded</option>
            <option value="processing">Processing</option>
            <option value="on-hold">On Hold</option>
            <option value="cancelled">Cancelled</option>
          </select>
          <button onClick={()=>{setPage(1);load();}} style={{ ...S.btn, padding:'6px 13px' }}>Search</button>
          <div style={{ marginLeft:'auto', display:'flex', gap:8, alignItems:'center' }}>
            <span style={{ fontSize:12, color:T.mu }}>{total.toLocaleString()} orders</span>
            <ColChooser allCols={ALL_COLS} visible={vis} onChange={handleColChange}/>
            <button style={S.btnO}>Export order data</button>
            <button style={S.btn}>Export line item data</button>
          </div>
        </SearchBar>
        <Err msg={err}/>
        {loading ? <Spinner/> : (
          <div style={{ overflowX:'auto' }}>
            <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
              <thead><tr>
                <th style={S.th}></th>
                {ALL_COLS.filter(c=>vis.includes(c.key)).map(c => (
                  <th key={c.key} style={{ ...S.th, textAlign:['total_quantity','total','shipping_total','payment_fee','total_tax','refund_total'].includes(c.key)?'right':'left' }}>
                    {c.label}
                  </th>
                ))}
              </tr></thead>
              <tbody>
                {rows.map(r => (
                  <React.Fragment key={r.id}>
                    <tr onMouseEnter={e=>e.currentTarget.style.background=T.div} onMouseLeave={e=>e.currentTarget.style.background=''}>
                      <td style={{ ...S.td, fontSize:15, fontWeight:700, color:T.pri, cursor:'pointer', textAlign:'center', width:30 }}
                        onClick={()=>expandOrder(r)}>{expanded===r.id?'−':'+'}</td>
                      {vis.includes('order_id')        && <td style={{ ...S.td, fontWeight:600, fontSize:14 }}>{r.order_id}</td>}
                      {vis.includes('order_number')     && <td style={{ ...S.td, color:T.pri, fontSize:14.5, cursor:'pointer' }} onClick={()=>expandOrder(r)}>{r.order_number}</td>}
                      {vis.includes('status')           && <td style={S.td}><StatusBadge status={r.status}/></td>}
                      {vis.includes('products') && <td style={{ ...S.td, minWidth:320, whiteSpace:'normal', lineHeight:1.6, fontSize:13, color:T.mu }}>{r.products_list||'—'}</td>}
                      {vis.includes('tracking_code')    && <td style={{ ...S.td, fontSize:14 }}>{r.tracking_code||'—'}</td>}
                      {vis.includes('landing_site')     && <td style={{ ...S.td, fontSize:14 }}>{r.landing_site||'direct'}</td>}
                      {vis.includes('first_name')       && <td style={{ ...S.td, whiteSpace:'nowrap' }}>{[r.first_name,r.last_name].filter(Boolean).join(' ')||'—'}</td>}
                      {vis.includes('email')            && <td style={{ ...S.td, fontSize:14, color:T.mu }}>{r.email||'—'}</td>}
                      {vis.includes('state')            && <td style={S.td}><span style={{ fontSize:13, background:T.div, padding:'2px 6px', borderRadius:4, color:T.tx2 }}>{r.state||'—'}</span></td>}
                      {vis.includes('total_quantity')   && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{fN(r.total_quantity)}</td>}
                      {vis.includes('total')            && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:600 }}>{f$2(r.total)}</td>}
                      {vis.includes('coupons')          && <td style={{ ...S.td, fontSize:14, color:T.pri }}>{r.coupons||'—'}</td>}
                      {vis.includes('shipping_total')   && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{f$2(r.shipping_total)}</td>}
                      {vis.includes('payment_fee')      && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.mu }}>{f$2(r.payment_fee)}</td>}
                      {vis.includes('total_tax')        && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{f$2(r.total_tax)}</td>}
                      {vis.includes('shipping_tax')     && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{f$2(r.shipping_tax)}</td>}
                      {vis.includes('refund_total')     && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:r.refund_total>0?T.red:T.tx2 }}>{f$2(r.refund_total)}</td>}
                      {vis.includes('payment_method_title') && <td style={{ ...S.td, fontSize:14 }}>{r.payment_method_title||'—'}</td>}
                      {vis.includes('date_created')     && <td style={{ ...S.td, fontSize:14, whiteSpace:'nowrap' }}>{fDate(r.date_created)}</td>}
                    </tr>
                    {expanded===r.id && (
                      <tr>
                        <td style={{ width:32, padding:0, background:T.div, position:'sticky', left:0, zIndex:1 }}/>
                        <td colSpan={vis.length} style={{ padding:0, background:T.div }}>
                          <div style={{ padding:'10px 16px' }}>
                            <div style={{ fontSize:13, fontWeight:700, color:T.tx, marginBottom:8 }}>Line Items — {r.order_number}</div>
                            <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
                              <thead><tr>
                                {['Product','SKU','Qty','Price','Subtotal','Tax','Discount','COGS','Type'].map(h=>(
                                  <th key={h} style={{ ...S.th, top:'auto' }}>{h}</th>
                                ))}
                              </tr></thead>
                              <tbody>
                                {expandedItems.map((li,j) => (
                                  <tr key={j} style={{ background:j%2===0?T.card:T.div }}>
                                    <td style={{ ...S.td, fontSize:14 }}>{li.parent_name||li.name}</td>
                                    <td style={{ ...S.td, fontSize:11, color:T.mu }}>{li.sku||'—'}</td>
                                    <td style={{ ...S.td, textAlign:'right' }}>{li.quantity}</td>
                                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{f$2(li.price)}</td>
                                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:600 }}>{f$2(li.subtotal)}</td>
                                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{f$2(li.total_tax)}</td>
                                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.ora }}>{f$2(li.discount_total)}</td>
                                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.red }}>{f$2(li.total_cogs)}</td>
                                    <td style={S.td}>{li.product_type ? <StatusBadge status={li.product_type}/> : '—'}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
                {rows.length===0 && <tr><td colSpan={vis.length+1} style={{ padding:40, textAlign:'center', color:T.mu, fontSize:13 }}>No orders found</td></tr>}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={page} pages={pages} total={total} per={PER} onPage={setPage}/>
      </TableWrap>
    </div>
  );
}

/* ── PAGE: PRODUCTS ───────────────────────────────────── */
function ProductsPage({ dates, websiteId }) {
  const [rows,    setRows]    = useState([]);
  const [total,   setTotal]   = useState(0);
  const [pages,   setPages]   = useState(1);
  const [page,    setPage]    = useState(1);
  const [search,  setSearch]  = useState('');
  const [loading, setLoading] = useState(false);
  const [imgPreview, setImgPreview] = useState(null);
  const [detail,  setDetail]  = useState(null);   // { name, internal_id }
  const [detailData, setDetailData] = useState(null);
  const [sortCol, setSortCol] = useState('date_modified');
  const [sortDir, setSortDir] = useState('desc');
  const PER = 20;

  const PROD_ALL_COLS = [
    { key:'image',        label:'Image' },
    { key:'product_id',   label:'Product ID' },
    { key:'platform',     label:'Platform' },
    { key:'website',      label:'Website' },
    { key:'name',         label:'Name' },
    { key:'status',       label:'Status' },
    { key:'categories',   label:'Categories' },
    { key:'tags',         label:'Tags' },
    { key:'date_created', label:'Created At' },
    { key:'date_modified',label:'Modified At' },
  ];
  const PROD_DEFAULT = ['image','product_id','platform','name','status','categories','tags','date_created','date_modified'];
  const [pVis, setPVis] = useState(PROD_DEFAULT);

  useEffect(() => {
    if (!dates?.start || !dates?.end) return;
    setLoading(true); setRows([]);
    api('/products', { start:dates.start, end:dates.end, website_id:websiteId, search, page, per:PER })
      .then(d => { setRows(d?.rows||[]); setTotal(d?.total||0); setPages(d?.pages||1); })
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [dates?.start, dates?.end, websiteId, search, page]);

  function openDetail(r) {
    setDetail({ name: r.name, internal_id: r.internal_id });
    setDetailData(null);
    api(`/products/${r.internal_id}/detail`)
      .then(d => setDetailData(d))
      .catch(() => setDetailData({ variants:[], gallery:[] }));
  }

  const sorted = [...rows].sort((a,b) => {
    const va = a[sortCol]||'', vb = b[sortCol]||'';
    return sortDir==='asc' ? (va>vb?1:-1) : (va<vb?1:-1);
  });

  return (
    <div>
      <ImageModal src={imgPreview} onClose={()=>setImgPreview(null)}/>

      {/* Product Detail Modal */}
      {detail && (
        <div style={{ position:'fixed', inset:0, background:'rgba(0,0,0,.45)', zIndex:900, display:'flex', alignItems:'center', justifyContent:'center' }}
             onClick={()=>setDetail(null)}>
          <div style={{ background:T.card, borderRadius:12, padding:28, width:'min(860px,92vw)', maxHeight:'85vh', overflowY:'auto', position:'relative' }}
               onClick={e=>e.stopPropagation()}>
            <button onClick={()=>setDetail(null)}
              style={{ position:'absolute', top:14, right:16, background:'none', border:'none', fontSize:22, cursor:'pointer', color:T.mu }}>✕</button>
            <div style={{ fontWeight:700, fontSize:15, marginBottom:18, paddingRight:32, color:T.tx }}>Product: {detail.name}</div>
            {!detailData ? <Spinner/> : (<>
              {/* Variants table */}
              <table style={{ width:'100%', borderCollapse:'collapse', fontSize:13, marginBottom:24 }}>
                <thead><tr style={{ background:T.div }}>
                  {['Image','Attribute','SKU','Status','Stock status','Regular price','Sale price','Created at'].map(h=>(
                    <th key={h} style={{ ...S.th, top:'auto', padding:'8px 10px', textAlign:h.includes('price')?'right':'left' }}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {(detailData.variants||[]).map((v,i) => (
                    <tr key={i} style={{ borderBottom:`1px solid ${T.bdr}` }}>
                      <td style={{ padding:'10px', width:52 }}>
                        {v.image
                          ? <img src={imgSrc(v.image)} style={{ width:44,height:44,objectFit:'cover',borderRadius:6,border:`1px solid ${T.bdr}` }} onError={e=>e.target.style.display='none'} alt=""/>
                          : <div style={{ width:44,height:44,borderRadius:6,background:T.div }}/>}
                      </td>
                      <td style={{ padding:'10px', color:T.mu }}>{v.attributes||'—'}</td>
                      <td style={{ padding:'10px', fontFamily:'monospace', fontSize:12 }}>{v.sku||'—'}</td>
                      <td style={{ padding:'10px' }}>{v.status ? <StatusBadge status={v.status}/> : '—'}</td>
                      <td style={{ padding:'10px', color:T.mu }}>{v.stock_status||'—'}</td>
                      <td style={{ padding:'10px', textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{v.regular_price>0?f$2(v.regular_price):'—'}</td>
                      <td style={{ padding:'10px', textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:600, color:T.grn }}>{v.sale_price>0?f$2(v.sale_price):'—'}</td>
                      <td style={{ padding:'10px', color:T.mu, fontSize:12, whiteSpace:'nowrap' }}>{fDateTime(v.created_at)}</td>
                    </tr>
                  ))}
                  {(detailData.variants||[]).length===0 && <tr><td colSpan={8} style={{ padding:24, textAlign:'center', color:T.mu }}>No variants found</td></tr>}
                </tbody>
              </table>
              {/* Gallery */}
              {(detailData.gallery||[]).length > 0 && (<>
                <div style={{ fontWeight:700, fontSize:14, marginBottom:12, color:T.tx }}>Galleries</div>
                <div style={{ display:'flex', flexWrap:'wrap', gap:8 }}>
                  {(detailData.gallery||[]).map((g,i) => (
                    <img key={i} src={g.src} alt={g.alt||''} title={g.name||''}
                      style={{ width:100,height:100,objectFit:'cover',borderRadius:8,border:`1px solid ${T.bdr}`,cursor:'pointer' }}
                      onClick={()=>setImgPreview(g.src)}
                      onError={e=>e.target.style.display='none'}/>
                  ))}
                </div>
              </>)}
            </>)}
          </div>
        </div>
      )}

      <KpiGrid cols={2}>
        <KpiCard label="Total Products" value={fN(total)} tooltip="Products created in selected date range"/>
        <KpiCard label="Showing page"   value={`${page} / ${pages}`} color={T.mu}/>
      </KpiGrid>
      <TableWrap>
        <SearchBar>
          <input placeholder="Search product name..." value={search}
            onChange={e=>{ setSearch(e.target.value); setPage(1); }} style={{ ...S.inp, width:240 }}/>
          <ColChooser allCols={PROD_ALL_COLS} visible={pVis}
            onChange={(k,v) => k==='__reset__' ? setPVis(PROD_DEFAULT) : setPVis(cv => v ? [...cv,k] : cv.filter(x=>x!==k))}/>
          <span style={{ marginLeft:'auto', fontSize:13, color:T.mu }}>{total.toLocaleString()} products</span>
        </SearchBar>
        {loading ? <Spinner/> : (
          <div style={{ overflowX:'auto' }}>
            <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
              <thead><tr>
                {pVis.includes('image')        && <th style={S.th}>Image</th>}
                {pVis.includes('product_id')   && <SortTh label="Product ID"   col="product_id"   sortCol={sortCol} sortDir={sortDir} onSort={c=>{setSortCol(c);setSortDir(d=>sortCol===c?d==='asc'?'desc':'asc':'desc');}}/>}
                {pVis.includes('platform')     && <SortTh label="Platform"     col="platform"     sortCol={sortCol} sortDir={sortDir} onSort={c=>{setSortCol(c);setSortDir(d=>sortCol===c?d==='asc'?'desc':'asc':'desc');}}/>}
                {pVis.includes('website')      && <SortTh label="Website"      col="website"      sortCol={sortCol} sortDir={sortDir} onSort={c=>{setSortCol(c);setSortDir(d=>sortCol===c?d==='asc'?'desc':'asc':'desc');}}/>}
                {pVis.includes('name')         && <SortTh label="Name"         col="name"         sortCol={sortCol} sortDir={sortDir} onSort={c=>{setSortCol(c);setSortDir(d=>sortCol===c?d==='asc'?'desc':'asc':'desc');}} style={{ minWidth:260 }}/>}
                {pVis.includes('status')       && <SortTh label="Status"       col="status"       sortCol={sortCol} sortDir={sortDir} onSort={c=>{setSortCol(c);setSortDir(d=>sortCol===c?d==='asc'?'desc':'asc':'desc');}}/>}
                {pVis.includes('categories')   && <th style={{ ...S.th, minWidth:180 }}>Categories</th>}
                {pVis.includes('tags')         && <th style={{ ...S.th, minWidth:280 }}>Tags</th>}
                {pVis.includes('date_created') && <SortTh label="Created At"   col="date_created" sortCol={sortCol} sortDir={sortDir} onSort={c=>{setSortCol(c);setSortDir(d=>sortCol===c?d==='asc'?'desc':'asc':'desc');}} style={{ whiteSpace:'nowrap' }}/>}
                {pVis.includes('date_modified')&& <SortTh label="Modified At"  col="date_modified"sortCol={sortCol} sortDir={sortDir} onSort={c=>{setSortCol(c);setSortDir(d=>sortCol===c?d==='asc'?'desc':'asc':'desc');}} style={{ whiteSpace:'nowrap' }}/>}
              </tr></thead>
              <tbody>
                {sorted.map((r,i) => (
                  <tr key={i} onMouseEnter={e=>e.currentTarget.style.background=T.div} onMouseLeave={e=>e.currentTarget.style.background=''}>
                    {pVis.includes('image') && (
                      <td style={{ ...S.td, cursor:'pointer' }} onClick={()=>r.image&&setImgPreview(imgSrc(r.image))}>
                        {imgSrc(r.image)
                          ? <img src={imgSrc(r.image)} style={{ width:44,height:44,borderRadius:6,objectFit:'cover',border:`1px solid ${T.bdr}` }} onError={e=>{e.target.style.display='none';}} alt="" title="Click to preview"/>
                          : <div style={{ width:44,height:44,borderRadius:6,background:T.div,display:'flex',alignItems:'center',justifyContent:'center',fontSize:10,color:T.mu }}>IMG</div>}
                      </td>
                    )}
                    {pVis.includes('product_id')    && <td style={{ ...S.td, fontSize:13, color:T.pri, fontFamily:'monospace', cursor:'pointer', textDecoration:'underline' }}
                                                            onClick={()=>openDetail(r)}>{r.product_id||'—'}</td>}
                    {pVis.includes('platform')      && <td style={{ ...S.td, fontSize:13, color:T.mu }}>{r.platform||'—'}</td>}
                    {pVis.includes('website')       && <td style={{ ...S.td, fontSize:13, color:T.mu }}>{r.website||'—'}</td>}
                    {pVis.includes('name')          && <td style={{ ...S.td, fontWeight:600, color:T.tx, minWidth:260, whiteSpace:'normal', lineHeight:1.4 }}>{r.name}</td>}
                    {pVis.includes('status')        && <td style={S.td}>{r.status ? <StatusBadge status={r.status}/> : '—'}</td>}
                    {pVis.includes('categories')    && <td style={{ ...S.td, minWidth:180, fontSize:13, color:T.mu, whiteSpace:'normal' }}>{r.categories||'—'}</td>}
                    {pVis.includes('tags')          && <td style={{ ...S.td, minWidth:280, whiteSpace:'normal' }}><Tags tags={r.tags} clickable/></td>}
                    {pVis.includes('date_created')  && <td style={{ ...S.td, fontSize:13, color:T.mu, whiteSpace:'nowrap' }}>{fDateTime(r.date_created)}</td>}
                    {pVis.includes('date_modified') && <td style={{ ...S.td, fontSize:13, color:T.mu, whiteSpace:'nowrap' }}>{fDateTime(r.date_modified)}</td>}
                  </tr>
                ))}
                {rows.length===0 && <tr><td colSpan={pVis.length||9} style={{ padding:40, textAlign:'center', color:T.mu }}>
                  {!dates?.start ? 'Please select a date range' : 'No products found'}
                </td></tr>}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={page} pages={pages} total={total} per={PER} onPage={setPage}/>
      </TableWrap>
    </div>
  );
}

/* ── PAGE: PRODUCT REPORT ─────────────────────────────── */
function ProductReportPage({ dates, websiteId }) {
  const [rows,  setRows]  = useState([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [search, setSearch] = useState('');
  const [page,  setPage]  = useState(1);
  const [loading, setLoading] = useState(false);
  const [imgPreview, setImgPreview] = useState(null);
  const [kpi, setKpi] = useState({});
  const [kpiPrev, setKpiPrev] = useState({});
  const [expandedPR, setExpandedPR] = useState(null);
  const PER = 50;
  const PR_ALL_COLS = [
    { key:'image', label:'Image' }, { key:'parent_name', label:'Parent Name' },
    { key:'parent_sku', label:'Product Code (SKU)' }, { key:'product_type', label:'Product Type' },
    { key:'total_orders', label:'Orders' }, { key:'product_quantity', label:'Qty' },
    { key:'sub_total', label:'Sub Total' }, { key:'total_taxes', label:'Taxes' },
    { key:'discount', label:'Discount' }, { key:'total_cogs', label:'Cogs' },
    { key:'google_ads_cost', label:'GG Ads Cost' }, { key:'google_ads_revenue', label:'GG Ads Rev' },
    { key:'platform', label:'Platform' }, { key:'website_name', label:'Website' },
    { key:'tags', label:'Tags' }, { key:'date_created', label:'Date Created' },
  ];
  const PR_DEFAULT = ['image','parent_name','parent_sku','product_type','total_orders','product_quantity','sub_total','total_cogs','google_ads_cost','google_ads_revenue','platform','website_name','tags'];
  const [prVis, setPrVis] = useState(PR_DEFAULT);

  useEffect(() => {
    if (!dates?.start || !dates?.end) { setLoading(false); return; }
    setLoading(true);
    api('/product-report', { start:dates.start, end:dates.end, website_id:websiteId, product_name:search, page, per:PER })
      .then(d => {
        if (d?.rows) { setRows(d.rows); setTotal(d.total||0); setPages(d.pages||1); }
        else { setRows(d||[]); setTotal((d||[]).length); }
      }).finally(() => setLoading(false));
    // KPI deltas
    if (dates.start) {
      api('/exec/kpis', { start:dates.start, end:dates.end, website_id:websiteId }).then(setKpi).catch(()=>{});
      const ds=new Date(dates.start+'T12:00:00'), de=new Date(dates.end+'T12:00:00');
      const days=Math.round((de-ds)/86400000)+1;
      const pe=new Date(ds); pe.setDate(pe.getDate()-1);
      const ps=new Date(pe); ps.setDate(ps.getDate()-days+1);
      const fmt=d=>d.toISOString().slice(0,10);
      api('/exec/kpis', { start:fmt(ps), end:fmt(pe), website_id:websiteId }).then(setKpiPrev).catch(()=>{});
    }
  }, [dates.start, dates.end, websiteId, search, page]);

  const totals = (Array.isArray(rows)?rows:[]).reduce((a,r) => ({
    products:rows.length, qty:a.qty+(+r.product_quantity||0),
    sub:a.sub+(+r.sub_total||0), cogs:a.cogs+(+r.total_cogs||0),
  }), { products:0, qty:0, sub:0, cogs:0 });

  if (!dates?.start) return <Spinner/>;
  return (
    <div>
      <ImageModal src={imgPreview} onClose={()=>setImgPreview(null)}/>
      <KpiGrid cols={4}>
        <KpiCard label="Unique Products" value={fN(total||rows.length)}
          tooltip="Distinct parent products with orders in selected period"/>
        <KpiCard label="Total Revenue" value={f$2(kpi.revenue||0)} color={T.grn}
          delta={kpiPrev.revenue>0?((+(kpi.revenue||0)-kpiPrev.revenue)/kpiPrev.revenue*100):null}
          tooltip="Total sales revenue in selected period"/>
        <KpiCard label="Net Profit" value={f$2(kpi.net_profit||0)} color={(+(kpi.net_profit||0))>0?T.grn:T.red}
          delta={kpiPrev.net_profit&&Math.abs(kpiPrev.net_profit)>0?((+(kpi.net_profit||0)-kpiPrev.net_profit)/Math.abs(kpiPrev.net_profit)*100):null}
          tooltip="Revenue - COGS - Tax - Fees - Ads - Refunds"/>
        <KpiCard label="Total COGS" value={f$2(totals.cogs)} color={T.red}
          tooltip="Total cost of goods sold in selected period"/>
      </KpiGrid>
      <TableWrap>
        <SearchBar>
          <input placeholder="Search product name..." value={search}
            onChange={e=>{ setSearch(e.target.value); setPage(1); }} style={{ ...S.inp, width:220 }}/>
          <button onClick={()=>setPage(1)} style={{ ...S.btn, padding:'6px 13px' }}>Filter</button>
          <span style={{ fontSize:13, color:T.mu }}>{(total||rows.length).toLocaleString()} products</span>
        </SearchBar>
        {loading ? <Spinner/> : (
          <div style={{ overflowX:'auto' }}>
            <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
              <thead><tr>
                <th style={S.th}></th>
                <th style={S.th}>Image</th>
                <th style={S.th}>Parent Name</th>
                <th style={S.th}>Product Code</th>
                <th style={S.th}>Product Type</th>
                <th style={S.th}>Parent SKU</th>
                <th style={{ ...S.th, textAlign:'right' }}>Orders</th>
                <th style={{ ...S.th, textAlign:'right' }}>Qty</th>
                <th style={{ ...S.th, textAlign:'right' }}>Sub Total</th>
                <th style={{ ...S.th, textAlign:'right' }}>Taxes</th>
                <th style={{ ...S.th, textAlign:'right' }}>Discount</th>
                <th style={{ ...S.th, textAlign:'right' }}>Cogs</th>
                <th style={{ ...S.th, textAlign:'right' }}>GG Ads Cost</th>
                <th style={{ ...S.th, textAlign:'right' }}>GG Ads Rev</th>
                <th style={S.th}>Platform</th>
                <th style={S.th}>Website</th>
                <th style={S.th}>Tags</th>
                <th style={S.th}>Date Created</th>
              </tr></thead>
              <tbody>
                {rows.map((p,i) => (
                  <tr key={i} onMouseEnter={e=>e.currentTarget.style.background=T.div} onMouseLeave={e=>e.currentTarget.style.background=''}>
                    <td style={{ ...S.td, fontSize:15, fontWeight:700, color:T.pri, cursor:'pointer', textAlign:'center', width:32 }}
                      onClick={()=>setExpandedPR(expandedPR===i?null:i)}>{expandedPR===i?'−':'+'}</td>
                    {prVis.includes('image') && <td style={{ ...S.td, cursor:p.image?'zoom-in':'default' }} onClick={()=>p.image&&setImgPreview(p.image)}>
                      {p.image
                        ? <img src={p.image} style={{ width:38,height:38,borderRadius:5,objectFit:'cover',border:`1px solid ${T.bdr}` }} onError={e=>e.target.style.display='none'} alt=""/>
                        : <div style={{ width:38,height:38,borderRadius:5,background:T.div,display:'flex',alignItems:'center',justifyContent:'center',fontSize:10,color:T.mu }}>—</div>}
                    </td>}
                    {prVis.includes('parent_name')  && <td style={{ ...S.td, fontWeight:600, color:T.tx, minWidth:260, whiteSpace:'normal', lineHeight:1.4 }}>{p.parent_name}</td>}
                    {prVis.includes('parent_sku')  && <td style={{ ...S.td, fontSize:14, color:T.mu, fontFamily:'monospace' }}>{p.parent_sku||'—'}</td>}
                    {prVis.includes('product_type') && <td style={S.td}>{p.product_type ? <StatusBadge status={p.product_type}/> : '—'}</td>}
                    <td style={{ ...S.td, fontSize:14, color:T.mu }}>{p.parent_sku||'—'}</td>
                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:600 }}>{fN(p.total_orders)}</td>
                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{fN(p.product_quantity)}</td>
                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:600, color:T.grn }}>{f$(p.sub_total)}</td>
                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{f$(p.total_taxes)}</td>
                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.ora }}>{f$(p.discount)}</td>
                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.red }}>{f$(p.total_cogs)}</td>
                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.ora }}>{f$(p.google_ads_cost)}</td>
                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.grn }}>{f$(p.google_ads_revenue)}</td>
                    <td style={S.td}>{p.platform||'—'}</td>
                    <td style={{ ...S.td, fontSize:14 }}>{p.website_name||'—'}</td>
                    <td style={S.td}><Tags tags={p.tags} clickable/></td>
                    <td style={{ ...S.td, fontSize:14, color:T.mu, whiteSpace:'nowrap' }}>{fDate(p.date_created)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </TableWrap>
    </div>
  );
}

/* ── PAGE: PLATFORM REPORT ────────────────────────────── */
function PlatformPage({ dates, websiteId, websites }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState({});
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [sortCol, setSortCol] = useState('date_revenue');
  const [sortDir, setSortDir] = useState('desc');
  const PER = 50;

  const PLAT_ALL_COLS = [
    { key:'date_revenue',  label:'Date' },
    { key:'website_name',  label:'Website' },
    { key:'landing_site',  label:'Platform' },
    { key:'total_sales',   label:'Revenue' },
    { key:'total_orders',  label:'Orders' },
    { key:'total_quantity',label:'Qty' },
    { key:'total_cogs',    label:'COGS' },
    { key:'total_refunds', label:'Refunds' },
    { key:'tip',           label:'Tips' },
    { key:'payment_fee',   label:'Payment Fee' },
    { key:'total_tax',     label:'Tax' },
    { key:'shipping_total',label:'Shipping' },
    { key:'discount_total',label:'Discount' },
  ];
  const PLAT_DEFAULT = ['date_revenue','website_name','landing_site','total_sales','total_orders','total_quantity','total_cogs','total_refunds'];
  const [platVis, setPlatVis] = useState(PLAT_DEFAULT);

  useEffect(() => {
    if (!dates?.start || !dates?.end) return;
    setLoading(true);
    Promise.all([
      api('/platform-report', { start:dates.start, end:dates.end, website_id:websiteId, search, page, per:PER }),
      api('/platform-report/summary', { start:dates.start, end:dates.end, website_id:websiteId }),
    ]).then(([r, s]) => {
      const list = r?.rows || (Array.isArray(r) ? r : []);
      setRows(list);
      setTotal(r?.total || list.length);
      setPages(r?.pages || 1);
      setSummary(s||{});
    }).finally(() => setLoading(false));
  }, [dates?.start, dates?.end, websiteId, search, page]);

  const PLAT_COLORS = { google:'#4285F4', facebook:'#1877F2', direct:T.mu, omnisend:T.pur, bing:'#00B4D8', 'shop.app':T.grn };

  const sorted = [...rows].sort((a,b) => {
    const v1 = a[sortCol], v2 = b[sortCol];
    const n1 = parseFloat(v1)||0, n2 = parseFloat(v2)||0;
    return sortDir==='asc' ? n1-n2 : n2-n1;
  });

  const handleSort = col => {
    if (sortCol===col) setSortDir(d=>d==='asc'?'desc':'asc');
    else { setSortCol(col); setSortDir('desc'); }
  };

  if (!dates?.start) return <Spinner/>;
  return (
    <div>
      <KpiGrid cols={4}>
        <KpiCard label="Total Sales"   value={f$2(+(summary.sale_display||summary.revenue||0))} delta={summary.delta_revenue} color={T.grn}
          tooltip="Total order value in the selected period (excl. tips)"/>
        <KpiCard label="Total Orders"  value={fN(summary.orders)} delta={summary.delta_orders}
          tooltip="Total number of orders"/>
        <KpiCard label="Net Profit"    value={f$2(+(summary.net_profit||0))} color={(+summary.net_profit)>0?T.grn:T.red} delta={summary.delta_net_profit}
          tooltip="Revenue - COGS - Tax - Fees - Ads - Refunds"/>
        <KpiCard label="Blended ROAS"  value={fX(+(summary.roas||0))} color={(+summary.roas)>=4?T.grn:T.ora} delta={summary.delta_roas}
          tooltip="Revenue / Total Ad Spend"/>
      </KpiGrid>
      <div style={{ background:T.prib, border:`1px solid #C3D5FF`, borderRadius:8, padding:'9px 14px', marginBottom:12, fontSize:13, color:T.tx2 }}>
        <b style={{ color:T.pritx }}>Platform</b> = traffic source of each order (landing_site field). Values: google, facebook, direct, omnisend, bing, shop.app, etc.
      </div>
      <div style={{ background:T.div, borderRadius:8, padding:'8px 14px', marginBottom:12, display:'flex', gap:20, flexWrap:'wrap', fontSize:13 }}>
        <span style={{ color:T.mu }}>Period totals:</span>
        <span><b style={{ color:T.tx2 }}>{f$2(+(summary.shipping||0))}</b> <span style={{ color:T.mu }}>Shipping</span></span>
        <span><b style={{ color:T.tx2 }}>{f$2(+(summary.total_tax||0))}</b> <span style={{ color:T.mu }}>Tax</span></span>
        <span><b style={{ color:T.tx2 }}>{f$2(+(summary.discounts||0))}</b> <span style={{ color:T.mu }}>Discount</span></span>
        <span><b style={{ color:T.tx2 }}>{f$2(+(summary.payment_fee||0))}</b> <span style={{ color:T.mu }}>Pay Fee</span></span>
        <span><b style={{ color:T.red }}>{f$2(+(summary.refunds||0))}</b> <span style={{ color:T.mu }}>Refunds</span></span>
      </div>
      <TableWrap>
        <SearchBar>
          <input placeholder="Search platform..." value={search}
            onChange={e=>{ setSearch(e.target.value); setPage(1); }} style={{ ...S.inp, width:180 }}/>
          <span style={{ fontSize:13, color:T.mu }}>{total.toLocaleString()} rows</span>
          <ColChooser allCols={PLAT_ALL_COLS} visible={platVis}
            onChange={(k,v) => k==='__reset__' ? setPlatVis(PLAT_DEFAULT) : setPlatVis(cv => v ? [...cv,k] : cv.filter(x=>x!==k))}/>
        </SearchBar>
        {loading ? <Spinner/> : (
          <div style={{ overflowX:'auto', maxHeight:560, overflowY:'auto' }}>
            <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
              <thead><tr>
                <SortTh label="Website"     col="website"       sortCol={sortCol} sortDir={sortDir} onSort={handleSort}/>
                <SortTh label="Date"        col="date_revenue"  sortCol={sortCol} sortDir={sortDir} onSort={handleSort}/>
                <th style={S.th}>Platform</th>
                <SortTh label="Orders"      col="total_order"   sortCol={sortCol} sortDir={sortDir} onSort={handleSort}/>
                <SortTh label="Quantity"    col="total_quantity" sortCol={sortCol} sortDir={sortDir} onSort={handleSort}/>
                <SortTh label="Total Sales" col="total_sales"   sortCol={sortCol} sortDir={sortDir} onSort={handleSort}/>
                <SortTh label="Tip"         col="tip"           sortCol={sortCol} sortDir={sortDir} onSort={handleSort}/>
                <SortTh label="Cogs"        col="total_cogs"    sortCol={sortCol} sortDir={sortDir} onSort={handleSort}/>
                <SortTh label="Shipping"    col="shipping_total" sortCol={sortCol} sortDir={sortDir} onSort={handleSort}/>
                <SortTh label="Discount"    col="discount_total" sortCol={sortCol} sortDir={sortDir} onSort={handleSort}/>
                <SortTh label="Tax"         col="total_tax"     sortCol={sortCol} sortDir={sortDir} onSort={handleSort}/>
                <SortTh label="Pay Fee"     col="payment_fee"   sortCol={sortCol} sortDir={sortDir} onSort={handleSort}/>
                <SortTh label="Refunds"     col="total_refunds" sortCol={sortCol} sortDir={sortDir} onSort={handleSort}/>
              </tr></thead>
              <tbody>
                {sorted.map((r,i) => (
                  <tr key={i} onMouseEnter={e=>e.currentTarget.style.background=T.div} onMouseLeave={e=>e.currentTarget.style.background=''}>
                    <td style={S.td}>{r.website}</td>
                    <td style={{ ...S.td, whiteSpace:'nowrap', fontSize:14, color:T.mu }}>{fDate(r.date_revenue)}</td>
                    <td style={S.td}>
                      <span style={{ fontSize:11.5, fontWeight:600, padding:'2px 8px', borderRadius:10,
                        background:(PLAT_COLORS[r.platform]||T.pri)+'22', color:PLAT_COLORS[r.platform]||T.pri }}>
                        {r.platform}
                      </span>
                    </td>
                    {['total_order','total_quantity'].map(k => (
                      <td key={k} style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{fN(r[k])}</td>
                    ))}
                    {['total_sales','tip','total_cogs','shipping_total','discount_total','total_tax','payment_fee','total_refunds'].map(k => (
                      <td key={k} style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums',
                        color:k==='total_sales'?T.grn:k==='total_cogs'||k==='total_refunds'?T.red:T.tx2,
                        fontWeight:k==='total_sales'?600:400 }}>
                        {f$2(r[k])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={page} pages={pages} total={total} per={PER} onPage={p=>setPage(p)}/>
      </TableWrap>
    </div>
  );
}

/* ── PAGE: FACEBOOK ADS ───────────────────────────────── */
function FbAdsPage({ dates, websiteId }) {
  const [rows,        setRows]        = useState([]);
  const [total,       setTotal]       = useState(0);
  const [pages,       setPages]       = useState(1);
  const [summary,     setSummary]     = useState({});
  const [summaryPrev, setSummaryPrev] = useState({});
  const [search,  setSearch]  = useState('');
  const [account, setAccount] = useState('all');
  const [page,    setPage]    = useState(1);
  const [loading, setLoading] = useState(true);
  const [expandedRow, setExpandedRow] = useState(null);
  const FB_ALL_COLS = [
    { key:'campaign_name', label:'Campaign Name' },
    { key:'account_name',  label:'Account' },
    { key:'date',          label:'Date' },
    { key:'spend',         label:'Spend' },
    { key:'revenue',       label:'Revenue' },
    { key:'impressions',   label:'Impressions' },
    { key:'clicks',        label:'Clicks' },
    { key:'roas',          label:'ROAS' },
  ];
  const FB_DEFAULT = ['campaign_name','account_name','date','spend','revenue','impressions','clicks','roas'];
  const [fbVis, setFbVis] = useState(FB_DEFAULT);
  const [fbSort, setFbSort] = useState({ col:'spend', dir:'desc' });
  const PER = 50;

  useEffect(() => {
    setLoading(true);
    const ds=dates.start?new Date(dates.start+'T12:00:00'):null;
    const de=dates.end?new Date(dates.end+'T12:00:00'):null;
    const days=ds&&de?Math.round((de-ds)/86400000)+1:30;
    const pe=ds?new Date(ds):new Date(); pe.setDate(pe.getDate()-1);
    const ps=new Date(pe); ps.setDate(ps.getDate()-days+1);
    const fmt=d=>d.toISOString().slice(0,10);
    Promise.all([
      api('/facebook-ads', { start:dates.start, end:dates.end, website_id:websiteId, search, page, per:PER }),
      api('/facebook-ads/summary', { start:dates.start, end:dates.end, website_id:websiteId }),
      api('/facebook-ads/summary', { start:fmt(ps), end:fmt(pe), website_id:websiteId }),
    ]).then(([d, s, sp]) => {
      const filtered = (d.rows||[]).filter(r => account==='all' || r.account_name===account);
      setRows(filtered);
      setTotal(d.total||filtered.length);
      setPages(d.pages||1);
      setSummary(s||{});
      setSummaryPrev(sp||{});
    }).finally(() => setLoading(false));
  }, [dates.start, dates.end, websiteId, search, page, account]);

  // Get unique accounts
  const accounts = [...new Set(rows.map(r=>r.account_name).filter(Boolean))];

  return (
    <div>
      <KpiGrid cols={4}>
        <KpiCard label="Total Cost" value={f$2(summary.total_cost||0)} color={T.red}
          delta={summaryPrev.total_cost>0?((+(summary.total_cost||0)-summaryPrev.total_cost)/summaryPrev.total_cost*100):null}
          tooltip="Total ad spend across all campaigns in selected period"/>
        <KpiCard label="Total Revenue" value={f$2(summary.total_revenue||0)} color={T.grn}
          delta={summaryPrev.total_revenue>0?((+(summary.total_revenue||0)-summaryPrev.total_revenue)/summaryPrev.total_revenue*100):null}
          tooltip="Revenue attributed to Facebook campaigns"/>
        <KpiCard label="Blended ROAS" value={(+(summary.total_cost||0))>0?fX(+(summary.roas||0)):'—'}
          color={(+(summary.roas||0))>=4?T.grn:(+(summary.roas||0))>=2?T.ora:T.red}
          delta={summaryPrev.roas>0?((+(summary.roas||0)-summaryPrev.roas)/summaryPrev.roas*100):null}
          tooltip="Revenue / Spend. Target: 4x"/>
        <KpiCard label="Total Clicks" value={fN(summary.total_clicks||0)}
          delta={summaryPrev.total_clicks>0?((+(summary.total_clicks||0)-summaryPrev.total_clicks)/summaryPrev.total_clicks*100):null}
          tooltip="Total link clicks across all campaigns"/>
      </KpiGrid>
      <TableWrap>
        <SearchBar>
          <select name="account" value={account} onChange={e=>{ setAccount(e.target.value); setPage(1); }} style={S.sel}>
            <option value="all">All Accounts</option>
            {accounts.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
          <input placeholder="Search campaign..." value={search}
            onChange={e=>{ setSearch(e.target.value); setPage(1); }} style={{ ...S.inp, flex:1, minWidth:200 }}/>
          <span style={{ fontSize:13, color:T.mu }}>{total.toLocaleString()} ads</span>
          <ColChooser allCols={FB_ALL_COLS} visible={fbVis}
            onChange={(k,v) => k==='__reset__' ? setFbVis(FB_DEFAULT) : setFbVis(c => v ? [...c,k] : c.filter(x=>x!==k))}/>
        </SearchBar>
        {loading ? <Spinner/> : (
          <div style={{ overflowX:'auto', maxHeight:500, overflowY:'auto' }}>
            <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
              <thead><tr>
                <th style={S.th}></th>
                {fbVis.includes('campaign_name') && <SortTh label="Campaign" col="campaign_name" sortCol={fbSort.col} sortDir={fbSort.dir} onSort={col=>setFbSort(s=>({col,dir:s.col===col&&s.dir==='asc'?'desc':'asc'}))}/>}
                {fbVis.includes('account_name')  && <th style={S.th}>Account</th>}
                {fbVis.includes('date')          && <SortTh label="Date" col="date" sortCol={fbSort.col} sortDir={fbSort.dir} onSort={col=>setFbSort(s=>({col,dir:s.col===col&&s.dir==='asc'?'desc':'asc'}))}/>}
                {fbVis.includes('spend')         && <SortTh label="Spend" col="spend" sortCol={fbSort.col} sortDir={fbSort.dir} onSort={col=>setFbSort(s=>({col,dir:s.col===col&&s.dir==='asc'?'desc':'asc'}))}/>}
                {fbVis.includes('revenue')       && <SortTh label="Revenue" col="revenue" sortCol={fbSort.col} sortDir={fbSort.dir} onSort={col=>setFbSort(s=>({col,dir:s.col===col&&s.dir==='asc'?'desc':'asc'}))}/>}
                {fbVis.includes('impressions')   && <SortTh label="Impressions" col="impressions" sortCol={fbSort.col} sortDir={fbSort.dir} onSort={col=>setFbSort(s=>({col,dir:s.col===col&&s.dir==='asc'?'desc':'asc'}))}/>}
                {fbVis.includes('clicks')        && <SortTh label="Clicks" col="clicks" sortCol={fbSort.col} sortDir={fbSort.dir} onSort={col=>setFbSort(s=>({col,dir:s.col===col&&s.dir==='asc'?'desc':'asc'}))}/>}
                {fbVis.includes('roas')          && <SortTh label="ROAS" col="roas" sortCol={fbSort.col} sortDir={fbSort.dir} onSort={col=>setFbSort(s=>({col,dir:s.col===col&&s.dir==='asc'?'desc':'asc'}))}/>}
              </tr></thead>
              <tbody>
                {[...rows].sort((a,b)=>{
                    const va=parseFloat(a[fbSort.col])||0, vb=parseFloat(b[fbSort.col])||0;
                    return fbSort.dir==='asc'?va-vb:vb-va;
                  }).map((r,i) => {
                  const roas = r.spend>0 ? r.revenue/r.spend : 0;
                  return (
                    <React.Fragment key={i}>
                    <tr onMouseEnter={e=>e.currentTarget.style.background=T.div} onMouseLeave={e=>e.currentTarget.style.background=''}>
                      <td style={{ ...S.td, fontSize:15, fontWeight:700, color:T.pri, cursor:'pointer', textAlign:'center', width:30 }}
                        onClick={()=>setExpandedRow(expandedRow===i?null:i)}>
                        {expandedRow===i?'−':'+'}
                      </td>
                      <td style={{ ...S.td, maxWidth:240, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontWeight:600 }} title={r.campaign_name}>{r.campaign_name}</td>
                      <td style={S.td}><span style={{ fontSize:11.5, fontWeight:600, padding:'2px 7px', borderRadius:4, background:T.div, color:T.tx2 }}>{r.account_name||'—'}</span></td>
                      <td style={{ ...S.td, fontSize:14, color:T.mu, whiteSpace:'nowrap' }}>{r.date}</td>
                      {fbVis.includes('spend')       && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.red }}>{f$2(r.spend)}</td>}
                      {fbVis.includes('revenue')     && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.grn }}>{f$2(r.revenue)}</td>}
                      {fbVis.includes('impressions') && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{fN(r.impressions)}</td>}
                      {fbVis.includes('clicks')      && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{fN(r.clicks)}</td>}
                      {fbVis.includes('roas')        && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:600, color:roas>=4?T.grn:roas>=2?T.ora:roas>0?T.red:T.mu }}>{roas>0?fX(roas):'—'}</td>}
                    </tr>
                    {expandedRow===i && (
                      <tr>
                        <td colSpan={9} style={{ padding:0, background:T.div }}>
                          <div style={{ padding:'10px 20px' }}>
                            <div style={{ fontSize:13, color:T.tx2 }}>
                              Campaign: <b>{r.campaign_name}</b> &nbsp;|&nbsp; Status: <StatusBadge status={r.status||'—'}/> &nbsp;|&nbsp; Account: {r.account_name||r.account_origin_id||'—'}
                            </div>
                            <div style={{ fontSize:13, color:T.mu, marginTop:6, display:'flex', gap:16 }}>
                              <span>Spend: <b style={{color:T.red}}>{f$2(r.spend)}</b></span>
                              <span>Revenue: <b style={{color:T.grn}}>{f$2(r.revenue)}</b></span>
                              <span>ROAS: <b style={{color:r.spend>0&&r.revenue/r.spend>=4?T.grn:T.ora}}>{r.spend>0?fX(r.revenue/r.spend):'—'}</b></span>
                              <span>Impressions: <b>{fN(r.impressions)}</b></span>
                              <span>Clicks: <b>{fN(r.clicks)}</b></span>
                              <span>Conversions: <b>{r.conversions>0?(+r.conversions).toFixed(2):'—'}</b></span>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={page} pages={pages||Math.ceil(rows.length/PER)} total={total||rows.length} per={PER} onPage={p=>{setPage(p);}}/>
      </TableWrap>
    </div>
  );
}

/* ── PAGE: GOOGLE ADS ─────────────────────────────────── */
function GAdsPage({ dates, websiteId }) {
  const [tab, setTab] = useState('campaign');
  const [data, setData] = useState({ rows:[], summary:{} });
  const [prevSummary, setPrevSummary] = useState({});
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [loading, setLoading] = useState(true);
  const [gaPage, setGaPage] = useState(1);
  const [gaSortCol, setGaSortCol] = useState('cost');
  const [gaSortDir, setGaSortDir] = useState('desc');
  const [gaProductPage, setGaProductPage] = useState(1);
  const GA_PER = 50;
  const GA_PROD_COLS = [
    { key:'website_name', label:'Website' }, { key:'date', label:'Date' },
    { key:'product', label:'Product' }, { key:'product_id', label:'Product ID' },
    { key:'variant_id', label:'Variant ID' }, { key:'impressions', label:'Impressions' },
    { key:'clicks', label:'Clicks' }, { key:'cost', label:'Cost' },
    { key:'revenue', label:'Revenue' }, { key:'conversions', label:'Conv.' },
    { key:'roas', label:'ROAS' },
  ];
  const GA_PROD_DEFAULT = ['website_name','date','product','product_id','variant_id','impressions','clicks','cost','revenue','roas'];
  const [gaProdVis, setGaProdVis] = useState(GA_PROD_DEFAULT);
  const GA_CAMP_COLS = [
    { key:'website', label:'Website' }, { key:'date', label:'Date' },
    { key:'campaign_name', label:'Campaign' }, { key:'cost', label:'Cost' },
    { key:'impressions', label:'Impressions' }, { key:'clicks', label:'Clicks' },
    { key:'revenue', label:'Revenue' }, { key:'conversions', label:'Conv.' },
    { key:'roas', label:'ROAS' }, { key:'status', label:'Status' },
  ];
  const GA_DEFAULT = ['website','date','campaign_name','cost','impressions','clicks','revenue','roas','status'];
  const [gaVis, setGaVis] = useState(GA_DEFAULT);

  useEffect(() => {
    setLoading(true);
    const ep = tab==='campaign' ? '/google-ads' : '/google-ads/products';
    const dsGA=dates.start?new Date(dates.start+'T12:00:00'):null;
    const deGA=dates.end?new Date(dates.end+'T12:00:00'):null;
    const daysGA=dsGA&&deGA?Math.round((deGA-dsGA)/86400000)+1:30;
    const peGA=dsGA?new Date(dsGA):new Date(); peGA.setDate(peGA.getDate()-1);
    const psGA=new Date(peGA); psGA.setDate(psGA.getDate()-daysGA+1);
    const fmtGA=d=>d.toISOString().slice(0,10);
    const curPage = tab==='campaign' ? gaPage : gaProductPage;
    Promise.all([
      api(ep, { start:dates.start, end:dates.end, website_id:websiteId, search, status, page:curPage, per:GA_PER, sort:gaSortCol }),
      api('/google-ads', { start:fmtGA(psGA), end:fmtGA(peGA), website_id:websiteId, per:1 }),
    ]).then(([d, prev]) => { setData(d); setPrevSummary(prev?.summary||{}); })
      .finally(() => setLoading(false));
  }, [dates.start, dates.end, websiteId, tab, search, status, gaPage, gaProductPage, gaSortCol]);

  const s = data.summary || {};

  return (
    <div>
      <div style={{ display:'flex', borderBottom:`2px solid ${T.bdr}`, marginBottom:14 }}>
        {[{ v:'campaign', l:'Google Ads Summary' }, { v:'product', l:'Google Ads Product' }].map(t => (
          <button key={t.v} onClick={()=>setTab(t.v)}
            style={{ padding:'9px 20px', border:'none', background:'none', fontSize:13,
              color:tab===t.v?T.pri:T.mu, cursor:'pointer', fontFamily:'inherit',
              borderBottom:`2px solid ${tab===t.v?T.pri:'transparent'}`, marginBottom:-2,
              fontWeight:tab===t.v?600:400 }}>
            {t.l}
          </button>
        ))}
      </div>

      <KpiGrid cols={4}>
        <KpiCard label="Total Cost" value={f$2(s.total_cost||0)} color={T.red}
          delta={prevSummary.total_cost>0?((+(s.total_cost||0)-prevSummary.total_cost)/prevSummary.total_cost*100):null}
          tooltip="Total Google Ads spend in selected period"/>
        <KpiCard label="Total Revenue" value={f$2(s.total_revenue||0)} color={T.grn}
          delta={prevSummary.total_revenue>0?((+(s.total_revenue||0)-prevSummary.total_revenue)/prevSummary.total_revenue*100):null}
          tooltip="Revenue attributed to Google Ads campaigns"/>
        <KpiCard label="Blended ROAS" value={(+(s.total_cost||0))>0?fX(+(s.roas||0)):'—'}
          color={(+(s.roas||0))>=4?T.grn:(+(s.roas||0))>=2?T.ora:T.red}
          delta={prevSummary.roas>0?((+(s.roas||0)-prevSummary.roas)/prevSummary.roas*100):null}
          tooltip="Revenue / Spend. Target: 4x"/>
        <KpiCard label="Total Clicks" value={fN(s.total_clicks||0)}
          delta={prevSummary.total_clicks>0?((+(s.total_clicks||0)-prevSummary.total_clicks)/prevSummary.total_clicks*100):null}
          tooltip="Total clicks across all campaigns"/>
      </KpiGrid>

      <TableWrap>
        <SearchBar>
          <input placeholder={tab==='campaign'?'Search campaign...':'Search product...'}
            value={search} onChange={e=>{ setSearch(e.target.value); setGaPage(1); }} style={{ ...S.inp, width:220 }}/>
          {tab==='campaign' && (
            <select name="status" value={status} onChange={e=>{ setStatus(e.target.value); setGaPage(1); }} style={S.sel}>
              <option value="all">All Status</option>
              <option value="Active">Active</option>
              <option value="Paused">Paused</option>
            </select>
          )}
          <span style={{ fontSize:13, color:T.mu }}>
            {(data.total||(data.rows||[]).length).toLocaleString()} rows
          </span>
          {tab==='campaign' && (
            <ColChooser allCols={GA_CAMP_COLS} visible={gaVis}
              onChange={(k,v) => k==='__reset__' ? setGaVis(GA_DEFAULT) : setGaVis(cv => v ? [...cv,k] : cv.filter(x=>x!==k))}/>
          )}
          {tab!=='campaign' && (
            <ColChooser allCols={GA_PROD_COLS} visible={gaProdVis}
              onChange={(k,v) => k==='__reset__' ? setGaProdVis(GA_PROD_DEFAULT) : setGaProdVis(cv => v ? [...cv,k] : cv.filter(x=>x!==k))}/>
          )}
        </SearchBar>
        {loading ? <Spinner/> : (
          <div style={{ overflowX:'auto', maxHeight:560, overflowY:'auto' }}>
            {tab==='campaign' ? (
              <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
                <thead><tr>
                  <th style={S.th}>Website</th>
                  <th style={S.th}>Date</th>
                  <th style={S.th}>Campaign</th>
                  <th style={{ ...S.th, textAlign:'right' }}>Cost</th>
                  <th style={{ ...S.th, textAlign:'right' }}>Impressions</th>
                  <th style={{ ...S.th, textAlign:'right' }}>Clicks</th>
                  <th style={{ ...S.th, textAlign:'right' }}>Revenue</th>
                  <th style={{ ...S.th, textAlign:'right' }}>Conv.</th>
                  <th style={{ ...S.th, textAlign:'right' }}>ROAS</th>
                  <th style={S.th}>Status</th>
                </tr></thead>
                <tbody>
                  {[...(data.rows||[])].sort((a,b)=>{
                    const va=parseFloat(a[gaSortCol])||0, vb=parseFloat(b[gaSortCol])||0;
                    return gaSortDir==='asc'?va-vb:vb-va;
                  }).map((r,i) => (
                    <tr key={i} onMouseEnter={e=>e.currentTarget.style.background=T.div} onMouseLeave={e=>e.currentTarget.style.background=''}>
                      <td style={{ ...S.td, fontSize:14 }}>{r.website}</td>
                      <td style={{ ...S.td, fontSize:14, color:T.mu, whiteSpace:'nowrap' }}>{r.date}</td>
                      <td style={{ ...S.td, fontWeight:600, minWidth:200, fontSize:14, whiteSpace:'normal', lineHeight:1.4 }}>{r.campaign_name}</td>
                      <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.red }}>{f$2(r.cost)}</td>
                      <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{fN(r.impressions)}</td>
                      <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{fN(r.clicks)}</td>
                      <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.grn }}>{f$2(r.revenue)}</td>
                      <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{r.conversions>0?(+r.conversions).toFixed(2):'—'}</td>
                      <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:600,
                        color:r.roas>=4?T.grn:r.roas>=2?T.ora:r.roas>0?T.red:T.mu }}>
                        {r.roas>0?fX(r.roas):'—'}
                      </td>
                      <td style={S.td}><StatusBadge status={r.status}/></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
                <thead><tr>
                  {gaProdVis.includes('website_name') && <SortTh label="Website"     col="website_name" sortCol={gaSortCol} sortDir={gaSortDir} onSort={col=>{setGaSortCol(col);setGaSortDir(d=>gaSortCol===col?(d==='asc'?'desc':'asc'):'desc');}}/>}
                  {gaProdVis.includes('date')         && <th style={{ ...S.th, minWidth:110 }}>Date</th>}
                  {gaProdVis.includes('product')      && <th style={{ ...S.th, minWidth:200 }}>Product</th>}
                  {gaProdVis.includes('product_id')   && <th style={{ ...S.th, minWidth:130 }}>Product ID</th>}
                  {gaProdVis.includes('variant_id')   && <th style={{ ...S.th, minWidth:130 }}>Variant ID</th>}
                  {gaProdVis.includes('impressions')  && <SortTh label="Impressions" col="impressions"  sortCol={gaSortCol} sortDir={gaSortDir} onSort={col=>{setGaSortCol(col);setGaSortDir(d=>gaSortCol===col?(d==='asc'?'desc':'asc'):'desc');}}/>}
                  {gaProdVis.includes('clicks')       && <SortTh label="Clicks"      col="clicks"       sortCol={gaSortCol} sortDir={gaSortDir} onSort={col=>{setGaSortCol(col);setGaSortDir(d=>gaSortCol===col?(d==='asc'?'desc':'asc'):'desc');}}/>}
                  {gaProdVis.includes('cost')         && <SortTh label="Cost"        col="cost"         sortCol={gaSortCol} sortDir={gaSortDir} onSort={col=>{setGaSortCol(col);setGaSortDir(d=>gaSortCol===col?(d==='asc'?'desc':'asc'):'desc');}}/>}
                  {gaProdVis.includes('revenue')      && <SortTh label="Revenue"     col="revenue"      sortCol={gaSortCol} sortDir={gaSortDir} onSort={col=>{setGaSortCol(col);setGaSortDir(d=>gaSortCol===col?(d==='asc'?'desc':'asc'):'desc');}}/>}
                  {gaProdVis.includes('conversions')  && <th style={{ ...S.th, textAlign:'right' }}>Conv.</th>}
                  {gaProdVis.includes('roas')         && <SortTh label="ROAS"        col="roas"         sortCol={gaSortCol} sortDir={gaSortDir} onSort={col=>{setGaSortCol(col);setGaSortDir(d=>gaSortCol===col?(d==='asc'?'desc':'asc'):'desc');}}/>}
                </tr></thead>
                <tbody>
                  {(data.rows||[]).map((r,i) => (
                    <tr key={i} onMouseEnter={e=>e.currentTarget.style.background=T.div} onMouseLeave={e=>e.currentTarget.style.background=''}>
                      {gaProdVis.includes('website_name') && <td style={S.td}>{r.website_name}</td>}
                      {gaProdVis.includes('date')         && <td style={{ ...S.td, color:T.mu, whiteSpace:'nowrap', minWidth:110 }}>{r.date}</td>}
                      {gaProdVis.includes('product')      && <td style={{ ...S.td, minWidth:200, whiteSpace:'normal', lineHeight:1.4, color:T.pri }}>{r.product}</td>}
                      {gaProdVis.includes('product_id')   && <td style={{ ...S.td, fontSize:13, color:T.mu, minWidth:130 }}>{r.product_id}</td>}
                      {gaProdVis.includes('variant_id')   && <td style={{ ...S.td, fontSize:13, color:T.mu, minWidth:130 }}>{r.variant_id}</td>}
                      {gaProdVis.includes('impressions')  && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{fN(r.impressions)}</td>}
                      {gaProdVis.includes('clicks')       && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{fN(r.clicks)}</td>}
                      {gaProdVis.includes('cost')         && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.red }}>{f$2(+r.cost)}</td>}
                      {gaProdVis.includes('revenue')      && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.grn }}>{f$2(+r.revenue)}</td>}
                      {gaProdVis.includes('conversions')  && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{(+r.conversions)>0?(+r.conversions).toFixed(2):'—'}</td>}
                      {gaProdVis.includes('roas')         && <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:600, color:(+r.roas)>=4?T.grn:(+r.roas)>=2?T.ora:(+r.roas)>0?T.red:T.mu }}>{(+r.roas)>0?fX(+r.roas):'—'}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
        {tab==='campaign'
          ? <Pager page={gaPage} pages={data.pages||1} total={data.total||(data.rows||[]).length} per={GA_PER} onPage={setGaPage}/>
          : <Pager page={gaProductPage} pages={data.pages||1} total={data.total||(data.rows||[]).length} per={GA_PER} onPage={setGaProductPage}/>
        }
      </TableWrap>
    </div>
  );
}

/* ── PAGE: PROFIT ANALYTICS ───────────────────────────── */
function ProfitPage({ dates, websiteId }) {
  const [data, setData] = useState({ summary:{}, monthly:[], byStore:[] });
  const [prevKpi, setPrevKpi] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api('/profit', { start:dates.start, end:dates.end, website_id:websiteId })
      .then(setData).finally(() => setLoading(false));
    if (dates.start) {
      const ds=new Date(dates.start+'T12:00:00'), de=new Date(dates.end+'T12:00:00');
      const days=Math.round((de-ds)/86400000)+1;
      const pe=new Date(ds); pe.setDate(pe.getDate()-1);
      const ps=new Date(pe); ps.setDate(ps.getDate()-days+1);
      const fmt=d=>d.toISOString().slice(0,10);
      api('/exec/kpis', { start:fmt(ps), end:fmt(pe), website_id:websiteId }).then(setPrevKpi).catch(()=>{});
    }
  }, [dates.start, dates.end, websiteId]);

  if (loading) return <Spinner/>;
  const s = data.summary || {};
  const monthlyChart = [...(data.monthly||[])].reverse();

  const wf = [
    { name:'Revenue', v:+s.revenue, fill:T.pri },
    { name:'COGS',    v:-(+s.cogs), fill:T.red },
    { name:'Gr.Profit',v:+s.gross_profit, fill:T.grn },
    { name:'FB Ads',  v:-(+s.fb_ads), fill:T.red+'cc' },
    { name:'GG Ads',  v:-(+s.ga_ads), fill:T.red+'99' },
    { name:'Email',   v:-(+s.email_ads||0), fill:T.red+'77' },
    { name:'Shipping',v:-(+s.shipping), fill:T.ora },
    { name:'Tax',     v:-(+s.total_tax||0), fill:T.ora+'cc' },
    { name:'Refunds', v:-(+s.refunds), fill:T.ora+'99' },
    { name:'Net Profit',v:+s.net_profit, fill:s.net_profit>0?T.grn:T.red },
  ];

  return (
    <div>
      <KpiGrid cols={4}>
        <KpiCard label="Gross Revenue" value={f$2(+(s.revenue||0))}
          delta={prevKpi.revenue>0?((+(s.revenue||0)-prevKpi.revenue)/prevKpi.revenue*100):null}
          tooltip="Total revenue minus tips"/>
        <KpiCard label="Total Costs" value={f$2(+(s.cogs||0)+(+(s.total_ads||0))+(+(s.shipping||0))+(+(s.refunds||0))+(+(s.payment_fee||0)))} color={T.red}
          tooltip="COGS + Ads + Shipping + Refunds + Payment Fees"/>
        <KpiCard label="Net Profit" value={f$2(+(s.net_profit||0))} color={(+(s.net_profit||0))>0?T.grn:T.red}
          delta={prevKpi.net_profit&&Math.abs(prevKpi.net_profit)>0?((+(s.net_profit||0)-prevKpi.net_profit)/Math.abs(prevKpi.net_profit)*100):null}
          tooltip="Revenue - COGS - Tax - Payment Fee - Ads - Refunds"/>
        <KpiCard label="Net Margin" value={fP((+(s.revenue||0))>0?(+(s.net_profit||0))/(+(s.revenue||0))*100:0)} color={T.grn}
          delta={prevKpi.margin!=null?((+(s.revenue||0))>0?(+(s.net_profit||0))/(+(s.revenue||0))*100:0)-prevKpi.margin:null}
          tooltip="Net Profit / Revenue × 100"/>
      </KpiGrid>

      <Card>
        <CardTitle>Cost Waterfall Breakdown</CardTitle>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={wf}>
            <CartesianGrid {...ax.grid}/>
            <XAxis dataKey="name" {...ax.xProps} tick={{ fontSize:11.5, fill:T.mu }}/>
            <YAxis {...ax.yProps} tickFormatter={fAxis}/>
            <Tooltip formatter={v=>f$(v)}/>
            <Bar dataKey="v" name="Value" radius={[4,4,0,0]}>
              {wf.map((e,i) => <Cell key={i} fill={e.fill}/>)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </Card>

      <div style={{ display:'grid', gridTemplateColumns:'1.6fr 1fr', gap:12 }}>
        <Card style={{ margin:0 }}>
          <CardTitle>Monthly Net Profit Trend</CardTitle>
          <ResponsiveContainer width="100%" height={320}>
            <AreaChart data={monthlyChart} margin={{ top:20, right:16, left:0, bottom:0 }}>
              <CartesianGrid {...ax.grid}/>
              <XAxis dataKey="month" {...ax.xProps}/>
              <YAxis {...ax.yProps} tickFormatter={f$}/>
              <Tooltip content={<ChartTip/>}/>
              <Area type="monotone" dataKey="net_profit" name="Net Profit" stroke={T.grn} fill={T.grn+'22'} strokeWidth={2} dot={false}/>
            </AreaChart>
          </ResponsiveContainer>
        </Card>
        <TableWrap style={{ margin:0 }}>
          <div style={{ padding:'10px 14px', borderBottom:`1px solid ${T.bdr}` }}>
            <span style={{ fontSize:14, fontWeight:700, color:T.tx }}>P&L Detail</span>
          </div>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
            <tbody>
              {[
                { label:'Gross Revenue',  v:s.revenue,     pos:true  },
                { label:'COGS',           v:s.cogs,        neg:true  },
                { label:'Gross Profit',   v:s.gross_profit, bold:true },
                { label:'Facebook Ads',   v:s.fb_ads,      neg:true  },
                { label:'Google Ads',     v:s.ga_ads,      neg:true  },
                { label:'Email Ads',      v:s.email_ads,   neg:true  },
                { label:'Bing Ads',       v:s.bing_ads,    neg:true  },
                { label:'Shipping',       v:s.shipping,    neg:true  },
                { label:'Refunds',        v:s.refunds,     neg:true  },
                { label:'Payment Fees',   v:s.payment_fee, neg:true  },
                { label:'Net Profit',     v:s.net_profit,  bold:true, big:true },
              ].map((r,i) => (
                <tr key={i} style={{ background:i%2===0?'':T.div+'44' }}>
                  <td style={{ padding:'8px 14px', fontSize:r.big?16:14, fontWeight:r.bold?700:400, color:T.tx }}>{r.label}</td>
                  <td style={{ padding:'8px 14px', textAlign:'right', fontVariantNumeric:'tabular-nums', fontSize:r.big?16:14,
                    fontWeight:r.bold?700:400, color:r.neg?T.red:r.v>0?T.grn:T.tx }}>
                    {r.neg?'-':''}{f$2(Math.abs(r.v||0))}
                  </td>
                  <td style={{ padding:'7px 14px', textAlign:'right' }}>
                    <span style={{ fontSize:11, fontWeight:600, padding:'2px 5px', borderRadius:3,
                      background:r.neg?T.redb:T.grnb, color:r.neg?T.redtx:T.grntx }}>
                      {s.revenue>0?fP(Math.abs(r.v||0)/s.revenue*100):'—'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </div>
    </div>
  );
}

/* ── PAGE: CUSTOMERS ──────────────────────────────────── */
function CustomersPage({ dates, websiteId }) {
  const [data, setData] = useState({ summary:{}, byState:[], byCountry:[] });
  const [prevSummary, setPrevSummary] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api('/customers', { start:dates.start, end:dates.end, website_id:websiteId })
      .then(setData).finally(() => setLoading(false));
    if (dates.start) {
      const ds=new Date(dates.start+'T12:00:00'), de=new Date(dates.end+'T12:00:00');
      const days=Math.round((de-ds)/86400000)+1;
      const pe=new Date(ds); pe.setDate(pe.getDate()-1);
      const ps=new Date(pe); ps.setDate(ps.getDate()-days+1);
      const fmt=d=>d.toISOString().slice(0,10);
      api('/customers', { start:fmt(ps), end:fmt(pe), website_id:websiteId }).then(d=>setPrevSummary(d?.summary||{})).catch(()=>{});
    }
  }, [dates.start, dates.end, websiteId]);

  const { summary, byState, byCountry } = data;
  if (loading) return <Spinner/>;

  return (
    <div>
      <KpiGrid cols={4}>
        <KpiCard label="Total Customers" value={fN(summary.total_customers)}
          delta={prevSummary.total_customers>0?((+(summary.total_customers||0)-prevSummary.total_customers)/prevSummary.total_customers*100):null}
          tooltip="Unique customer emails in selected period"/>
        <KpiCard label="Total Orders" value={fN(summary.total_orders)}
          delta={prevSummary.total_orders>0?((+(summary.total_orders||0)-prevSummary.total_orders)/prevSummary.total_orders*100):null}
          tooltip="Total orders in selected period"/>
        <KpiCard label="Avg Order Value" value={f$2(summary.avg_order_value||0)}
          delta={prevSummary.avg_order_value>0?((+(summary.avg_order_value||0)-prevSummary.avg_order_value)/prevSummary.avg_order_value*100):null}
          tooltip="Average revenue per order"/>
        <KpiCard label="Est. LTV" value={summary.avg_order_value ? f$2((+summary.avg_order_value)*2.1) : '—'}
          tooltip="Estimated LTV = AOV × avg repeat orders (2.1x)"/>
      </KpiGrid>

      <div style={{ display:'grid', gridTemplateColumns:'1.5fr 1fr', gap:12 }}>
        <Card style={{ margin:0 }}>
          <CardTitle>Revenue by US State — Top 20</CardTitle>
          <ResponsiveContainer width="100%" height={380}>
            <BarChart data={byState} layout="vertical">
              <XAxis type="number" {...ax.xProps} tickFormatter={f$}/>
              <YAxis type="category" dataKey="state" {...ax.yProps} width={140} tick={{ fontSize:12, fill:T.mu }}/>
              <Tooltip content={<ChartTip/>}/>
              <Bar dataKey="revenue" name="Revenue" fill={T.pri} radius={[0,4,4,0]}/>
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
          <TableWrap style={{ margin:0 }}>
            <div style={{ padding:'10px 14px', borderBottom:`1px solid ${T.bdr}` }}>
              <span style={{ fontSize:14, fontWeight:700, color:T.tx }}>State Breakdown</span>
            </div>
            <div style={{ maxHeight:180, overflowY:'auto' }}>
              <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
                <thead><tr>
                  <th style={S.th}>State</th>
                  <th style={{ ...S.th, textAlign:'right' }}>Orders</th>
                  <th style={{ ...S.th, textAlign:'right' }}>Revenue</th>
                </tr></thead>
                <tbody>
                  {byState.slice(0,10).map((r,i) => (
                    <tr key={i} onMouseEnter={e=>e.currentTarget.style.background=T.div} onMouseLeave={e=>e.currentTarget.style.background=''}>
                      <td style={{ ...S.td, fontWeight:600 }}>{r.state}</td>
                      <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{fN(r.orders)}</td>
                      <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:600 }}>{f$(r.revenue)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </TableWrap>
          <TableWrap style={{ margin:0 }}>
            <div style={{ padding:'10px 14px', borderBottom:`1px solid ${T.bdr}` }}>
              <span style={{ fontSize:14, fontWeight:700, color:T.tx }}>Country Breakdown</span>
            </div>
            <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
              <thead><tr>
                <th style={S.th}>Country</th>
                <th style={{ ...S.th, textAlign:'right' }}>Orders</th>
                <th style={{ ...S.th, textAlign:'right' }}>Revenue</th>
              </tr></thead>
              <tbody>
                {byCountry.map((r,i) => (
                  <tr key={i} onMouseEnter={e=>e.currentTarget.style.background=T.div} onMouseLeave={e=>e.currentTarget.style.background=''}>
                    <td style={{ ...S.td, fontWeight:600 }}>{r.country}</td>
                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums' }}>{fN(r.orders)}</td>
                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:600 }}>{f$(r.revenue)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </div>
      </div>
    </div>
  );
}

/* ── PAGE: REFUNDS & COUPONS ──────────────────────────── */
function RefundsPage({ dates, websiteId }) {
  const [data, setData] = useState({ summary:{}, trend:[], coupons:[] });
  const [prevSummary, setPrevSummary] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api('/refunds', { start:dates.start, end:dates.end, website_id:websiteId })
      .then(setData).finally(() => setLoading(false));
    if (dates.start) {
      const ds=new Date(dates.start+'T12:00:00'), de=new Date(dates.end+'T12:00:00');
      const days=Math.round((de-ds)/86400000)+1;
      const pe=new Date(ds); pe.setDate(pe.getDate()-1);
      const ps=new Date(pe); ps.setDate(ps.getDate()-days+1);
      const fmt=d=>d.toISOString().slice(0,10);
      api('/refunds', { start:fmt(ps), end:fmt(pe), website_id:websiteId }).then(d=>setPrevSummary(d?.summary||{})).catch(()=>{});
    }
  }, [dates.start, dates.end, websiteId]);

  if (loading) return <Spinner/>;
  const { summary, trend, coupons } = data;
  const trendChart = trend.map(r => ({ ...r, date:fDateShort(r.date) }));
  const totalCouponDiscount = coupons.reduce((a,c) => a+(+c.total_discount||0), 0);
  const totalCouponUses     = coupons.reduce((a,c) => a+(+c.uses||0), 0);

  return (
    <div>
      <KpiGrid cols={4}>
        <KpiCard label="Total Refund Value" value={f$2(summary.refund_value||0)} color={T.red}
          delta={prevSummary.refund_value>0?((+(summary.refund_value||0)-prevSummary.refund_value)/prevSummary.refund_value*100):null}
          tooltip="Sum of all refund amounts in the selected period"/>
        <KpiCard label="Refunded Orders" value={fN(summary.refunded_orders||0)}
          delta={prevSummary.refunded_orders>0?((+(summary.refunded_orders||0)-prevSummary.refunded_orders)/prevSummary.refunded_orders*100):null}
          tooltip="Number of orders that had at least one refund"/>
        <KpiCard label="Coupons Used" value={fN(totalCouponUses)}
          tooltip="Total coupon redemptions in the selected period"/>
        <KpiCard label="Total Discount Given" value={f$2(totalCouponDiscount)} color={T.ora}
          tooltip="Total discount value applied via coupons"/>
      </KpiGrid>

      <Card>
        <CardTitle>Refund Trend</CardTitle>
        <ResponsiveContainer width="100%" height={380}>
          <BarChart data={trendChart} margin={{ top:48, right:24, left:0, bottom:0 }}>
              <CartesianGrid {...ax.grid}/>
              <XAxis dataKey="date" {...ax.xProps}/>
              <YAxis {...ax.yProps} tickFormatter={f$}/>
              <Tooltip content={<ChartTip/>}/>
              <Bar dataKey="amount" name="Refund Amount" fill={T.red} radius={[3,3,0,0]}/>
          </BarChart>
        </ResponsiveContainer>
      </Card>
      <div style={{ display:'grid', gridTemplateColumns:'1.2fr 1fr', gap:12, marginBottom:12 }}>
        <TableWrap style={{ margin:0 }}>
          <div style={{ padding:'10px 14px', borderBottom:`1px solid ${T.bdr}` }}>
            <span style={{ fontSize:15, fontWeight:700, color:T.tx }}>Top Coupons</span>
          </div>
          <div style={{ overflowY:'auto', maxHeight:260 }}>
            <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
              <thead><tr>
                <th style={S.th}>Code</th>
                <th style={{ ...S.th, textAlign:'right' }}>Uses</th>
                <th style={{ ...S.th, textAlign:'right' }}>Discount</th>
              </tr></thead>
              <tbody>
                {coupons.map((r,i) => (
                  <tr key={i} onMouseEnter={e=>e.currentTarget.style.background=T.div} onMouseLeave={e=>e.currentTarget.style.background=''}>
                    <td style={{ ...S.td, fontWeight:700, fontSize:14 }}>{r.code} <span style={{ fontSize:12, fontWeight:400, color:T.mu }}>{r.type}</span></td>
                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:600 }}>{fN(r.uses)}</td>
                    <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', color:T.ora }}>{f$2(r.total_discount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TableWrap>
        <Card style={{ margin:0 }}>
          <CardTitle>Coupon Impact Summary</CardTitle>
          {[
            { label:'Total Coupons Used',  v:fN(totalCouponUses),          c:T.pri },
            { label:'Total Discount',       v:f$2(totalCouponDiscount),     c:T.ora },
            { label:'Avg Discount/Coupon',  v:totalCouponUses>0?f$2(totalCouponDiscount/totalCouponUses):'—', c:T.tx },
            { label:'Most Used Coupon',     v:coupons[0]?.code||'—',        c:T.pri },
            { label:'Most Used Uses',       v:fN(coupons[0]?.uses),         c:T.tx },
            { label:'Highest Discount',     v:coupons.length?f$2(Math.max(...coupons.map(c=>+c.total_discount||0))):'—', c:T.grn },
          ].map((r,i)=>(
            <div key={i} style={{ display:'flex', justifyContent:'space-between', padding:'7px 0', borderBottom:`1px solid ${T.div}` }}>
              <span style={{ fontSize:14, color:T.mu }}>{r.label}</span>
              <span style={{ fontSize:15, fontWeight:700, color:r.c }}>{r.v}</span>
            </div>
          ))}
        </Card>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:12 }}>
        <Card style={{ margin:0 }}>
          <CardTitle>Refund Count vs Amount</CardTitle>
          <div style={{ padding:'10px 0' }}>
            {[
              { label:'Total Refunds',     v:fN(summary.total_refunds),    color:T.red },
              { label:'Refund Value',       v:f$2(summary.refund_value),    color:T.red },
              { label:'Refunded Orders',    v:fN(summary.refunded_orders),  color:T.ora },
              { label:'Avg Refund Amount',  v:summary.refunded_orders>0?f$2(summary.refund_value/summary.refunded_orders):'—', color:T.tx },
            ].map((r,i)=>(
              <div key={i} style={{ display:'flex', justifyContent:'space-between', padding:'8px 0', borderBottom:`1px solid ${T.div}` }}>
                <span style={{ fontSize:14, color:T.mu }}>{r.label}</span>
                <span style={{ fontSize:15, fontWeight:700, color:r.color }}>{r.v}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card style={{ margin:0 }}>
          <CardTitle>Coupon Impact</CardTitle>
          <div style={{ padding:'10px 0' }}>
            {[
              { label:'Total Coupons Used',  v:fN(totalCouponUses),         color:T.pri },
              { label:'Total Discount Given',v:f$2(totalCouponDiscount),    color:T.ora },
              { label:'Avg Discount/Coupon', v:totalCouponUses>0?f$2(totalCouponDiscount/totalCouponUses):'—', color:T.tx },
              { label:'Top Coupon',          v:coupons[0]?.code||'—',        color:T.pri },
            ].map((r,i)=>(
              <div key={i} style={{ display:'flex', justifyContent:'space-between', padding:'8px 0', borderBottom:`1px solid ${T.div}` }}>
                <span style={{ fontSize:14, color:T.mu }}>{r.label}</span>
                <span style={{ fontSize:15, fontWeight:700, color:r.color }}>{r.v}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
      <div style={{ marginTop:16 }}>
        <div style={{ fontSize:16, fontWeight:700, color:T.tx, marginBottom:10, display:'flex', alignItems:'center', gap:8 }}>
          <span style={{ width:4, height:20, background:T.pri, borderRadius:2, display:'inline-block' }}/>
          Alerts & Recommendations
        </div>
        <InsightCard title="Refund Rate Insight" body="Top refund causes: wrong item received, damaged in shipping, product not as described. Review packaging and product description accuracy to reduce rate."/>
        <InsightCard title="Coupon Strategy" body={`${totalCouponUses} coupons redeemed with $${(+totalCouponDiscount).toFixed(0)} total discount. Track coupon-attributed revenue vs discount cost to ensure positive ROI. Pause codes with discount rate > 15% on high-volume SKUs.`}/>
        <InsightCard title="Reduce Refund Rate" body="Actionable steps: (1) Add size charts and detailed product photos to reduce wrong-fit returns. (2) Improve packaging with bubble wrap for flag products. (3) Set clear delivery expectations at checkout to reduce 'not delivered' claims."/>
      </div>
    </div>
  );
}

/* ── PAGE: OPERATIONS ─────────────────────────────────── */
function OpsPage({ dates, websiteId }) {
  const [data, setData] = useState({ byStatus:[], byShipping:[] });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api('/operations', { start:dates.start, end:dates.end, website_id:websiteId })
      .then(setData).finally(() => setLoading(false));
  }, [dates.start, dates.end, websiteId]);

  if (loading) return <Spinner/>;
  const total = data.byStatus.reduce((a,r)=>a+(+r.count||0),0);
  const STATUS_COLORS = { paid:T.grn, completed:T.grn, processing:T.pri, refunded:T.red, cancelled:T.mu, 'on-hold':T.ora };
  const fulfilled = data.byStatus.filter(r=>['paid','completed'].includes((r.status||'').toLowerCase())).reduce((a,r)=>a+(+r.count||0),0);
  const processing = data.byStatus.find(r=>(r.status||'').toLowerCase()==='processing')?.count||0;
  const cancelled = data.byStatus.filter(r=>['cancelled','failed'].includes((r.status||'').toLowerCase())).reduce((a,r)=>a+(+r.count||0),0);
  const fulfillRate = total>0 ? (fulfilled/total*100).toFixed(1) : 0;

  return (
    <div>
      <KpiGrid cols={4}>
        <KpiCard label="Total Orders"    value={fN(total)} tooltip="All orders in selected period"/>
        <KpiCard label="Fulfilled"       value={fN(fulfilled)} color={T.grn}
          sub={`${fulfillRate}% fulfillment rate`} tooltip="Paid + Completed orders"/>
        <KpiCard label="Processing"      value={fN(processing)} color={T.pri} tooltip="Orders pending fulfillment"/>
        <KpiCard label="Cancelled/Failed" value={fN(cancelled)} color={T.red} tooltip="Cancelled or failed orders"/>
      </KpiGrid>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:12 }}>
        <Card style={{ margin:0 }}>
          <CardTitle>Order Status Breakdown</CardTitle>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie data={data.byStatus} dataKey="count" nameKey="status"
                cx="45%" cy="50%" innerRadius={55} outerRadius={90}
                label={({name,percent})=>`${(percent*100).toFixed(0)}%`} labelLine={false}>
                {data.byStatus.map((r,i) => (
                  <Cell key={i} fill={STATUS_COLORS[(r.status||'').toLowerCase()] || T.charts[i%T.charts.length]}/>
                ))}
              </Pie>
              <Tooltip formatter={v=>fN(v)}/>
              <Legend iconSize={10} wrapperStyle={{ fontSize:13 }}/>
            </PieChart>
          </ResponsiveContainer>
        </Card>
        <Card style={{ margin:0 }}>
          <CardTitle>Shipping Method Breakdown</CardTitle>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data.byShipping} layout="vertical" margin={{ top:8, right:24, left:8, bottom:8 }}>
              <XAxis type="number" {...ax.xProps}/>
              <YAxis type="category" dataKey="method_title" {...ax.yProps} width={130} tick={{ fontSize:12, fill:T.mu }}/>
              <Tooltip content={<ChartTip/>}/>
              <Bar dataKey="count" name="Orders" fill={T.pri} radius={[0,4,4,0]}/>
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:12 }}>
        <Card style={{ margin:0 }}>
          <CardTitle>Fulfillment Performance</CardTitle>
          {[
            { label:'Fulfillment Rate',   v:`${fulfillRate}%`, color:fulfillRate>=90?T.grn:fulfillRate>=70?T.ora:T.red },
            { label:'Fulfilled Orders',   v:fN(fulfilled),     color:T.grn },
            { label:'Processing Orders',  v:fN(processing),    color:T.pri },
            { label:'Cancelled/Failed',   v:fN(cancelled),     color:T.red },
            { label:'Other Statuses',     v:fN(total-fulfilled-processing-cancelled), color:T.mu },
          ].map((r,i)=>(
            <div key={i} style={{ display:'flex', justifyContent:'space-between', padding:'8px 0', borderBottom:`1px solid ${T.div}` }}>
              <span style={{ fontSize:14, color:T.mu }}>{r.label}</span>
              <span style={{ fontSize:15, fontWeight:700, color:r.color }}>{r.v}</span>
            </div>
          ))}
        </Card>
        <TableWrap style={{ margin:0 }}>
          <div style={{ padding:'10px 14px', borderBottom:`1px solid ${T.bdr}` }}>
            <span style={{ fontSize:15, fontWeight:700, color:T.tx }}>Status Detail</span>
          </div>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:14 }}>
            <thead><tr>
              <th style={S.th}>Status</th>
              <th style={{ ...S.th, textAlign:'right' }}>Orders</th>
              <th style={{ ...S.th, textAlign:'right' }}>Share</th>
            </tr></thead>
            <tbody>
              {data.byStatus.map((r,i)=>(
                <tr key={i} onMouseEnter={e=>e.currentTarget.style.background=T.div} onMouseLeave={e=>e.currentTarget.style.background=''}>
                  <td style={S.td}><StatusBadge status={r.status}/></td>
                  <td style={{ ...S.td, textAlign:'right', fontVariantNumeric:'tabular-nums', fontWeight:600 }}>{fN(r.count)}</td>
                  <td style={{ ...S.td, textAlign:'right' }}>
                    <span style={{ fontSize:12, fontWeight:600, padding:'2px 6px', borderRadius:4, background:T.div, color:T.tx2 }}>
                      {total>0?fP(r.count/total*100):'—'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </div>

      <InsightCard title="Fulfillment Health"
        body={`Fulfillment rate is ${fulfillRate}%. ${+fulfillRate>=90?'Excellent — well above the 90% industry benchmark.':+fulfillRate>=70?'Acceptable but below the 90% benchmark. Review processing queue.':'Below target. Investigate bottlenecks in order processing and supplier response times.'}`}/>
      <InsightCard title="Shipping Mix"
        body={`${data.byShipping.length} shipping methods active. Top method: ${data.byShipping[0]?.method_title||'—'} (${fN(data.byShipping[0]?.count||0)} orders). Consider consolidating low-volume methods to simplify operations.`}/>
    </div>
  );
}

/* ── PAGE: SHOP COMPARISON ────────────────────────────── */
function ShopCompPage({ dates }) {
  const [data, setData] = useState({ byStore:[], monthly:[] });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api('/shop-comparison', { start:dates.start, end:dates.end }).then(setData).finally(()=>setLoading(false));
  }, [dates.start, dates.end]);

  if (loading) return <Spinner/>;
  const { byStore, monthly } = data;
  const months = [...new Set(monthly.map(r=>r.month))].sort().slice(-6);
  const stores = [...new Set(monthly.map(r=>r.store))];
  const chartData = months.map(m => {
    const row = { month:m };
    stores.forEach(s => { const d=monthly.find(r=>r.month===m&&r.store===s); row[s]=d?+d.revenue:0; });
    return row;
  });

  // Revenue share pie data
  const totalRev = byStore.reduce((a,s)=>a+(+s.revenue||0),0);
  const pieData = byStore.map((s,i)=>({ name:s.store, value:+(+s.revenue||0).toFixed(2), fill:T.charts[i] }));

  return (
    <div>
      <div style={{ display:'grid', gridTemplateColumns:`repeat(${byStore.length||3},1fr)`, gap:12, marginBottom:14 }}>
        {byStore.map((s,i) => (
          <div key={i} style={{ ...S.card, padding:16, borderTop:`3px solid ${T.charts[i]||T.pri}` }}>
            <div style={{ fontSize:15, fontWeight:700, color:T.tx, marginBottom:12 }}>{s.store}</div>
            {[['Revenue',f$2(+s.revenue),T.tx,true],['Orders',fN(s.orders),T.tx,false],
              ['AOV',f$2(+s.aov),T.tx,false],
              ['ROAS',fX(+s.roas),(+s.roas)>=4?T.grn:T.ora,false],
              ['Net Profit',f$2(+s.net_profit),(+s.net_profit)>0?T.grn:T.red,false],
              ['Margin',fP(+s.margin),(+s.margin)>15?T.grn:T.ora,false],
              ['Ad Spend',f$2(+s.ad_spend),T.ora,false],
            ].map(([label,val,color,big],ri) => (
              <div key={ri} style={{ display:'flex', justifyContent:'space-between', marginBottom:8, paddingBottom:ri===0?8:0, borderBottom:ri===0?`1px solid ${T.bdr}`:'none' }}>
                <span style={{ fontSize:14, color:T.mu }}>{label}</span>
                <span style={{ fontSize:big?16:14, fontWeight:big?700:600, color }}>{val}</span>
              </div>
            ))}
          </div>
        ))}
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1.6fr 1fr', gap:12, marginBottom:12 }}>
        <Card style={{ margin:0 }}>
          <CardTitle>Revenue by Store — Monthly</CardTitle>
          <ResponsiveContainer width="100%" height={360}>
            <BarChart data={chartData}>
              <CartesianGrid {...ax.grid}/>
              <XAxis dataKey="month" {...ax.xProps}/>
              <YAxis {...ax.yProps} tickFormatter={v=>f$(+v)}/>
              <Tooltip content={<ChartTip/>}/>
              <Legend wrapperStyle={{ fontSize:13 }}/>
              {stores.map((s,i) => <Bar key={s} dataKey={s} name={s} fill={T.charts[i]} radius={[3,3,0,0]}/>)}
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card style={{ margin:0 }}>
          <CardTitle>Revenue Share</CardTitle>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie data={pieData} dataKey="value" nameKey="name" cx="45%" cy="45%"
                innerRadius={45} outerRadius={80} label={({percent})=>`${(percent*100).toFixed(0)}%`}
                labelLine={false}>
                {pieData.map((e,i)=><Cell key={i} fill={e.fill}/>)}
              </Pie>
              <Tooltip formatter={v=>f$2(+v)}/>
              <Legend iconSize={10} wrapperStyle={{ fontSize:13 }}/>
            </PieChart>
          </ResponsiveContainer>
          <div style={{ marginTop:12 }}>
            {byStore.map((s,i)=>(
              <div key={i} style={{ display:'flex', justifyContent:'space-between', padding:'5px 0', borderBottom:`1px solid ${T.div}` }}>
                <span style={{ fontSize:13, color:T.tx2 }}>{s.store}</span>
                <span style={{ fontSize:13, fontWeight:600, color:T.charts[i] }}>
                  {totalRev>0?fP((+s.revenue/totalRev)*100):'—'}
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12 }}>
        <Card style={{ margin:0 }}>
          <CardTitle>ROAS by Store</CardTitle>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={byStore.map(s=>({ name:s.store, roas:+(+s.roas).toFixed(2) }))}>
              <CartesianGrid {...ax.grid}/>
              <XAxis dataKey="name" {...ax.xProps} tick={{ fontSize:13, fill:T.mu }}/>
              <YAxis {...ax.yProps} tickFormatter={v=>v+'x'}/>
              <Tooltip formatter={v=>fX(+v)}/>
              <Bar dataKey="roas" name="ROAS" fill={T.pri} radius={[4,4,0,0]}>
                {byStore.map((s,i)=><Cell key={i} fill={(+s.roas)>=4?T.grn:(+s.roas)>=2?T.ora:T.red}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card style={{ margin:0 }}>
          <CardTitle>Net Margin by Store</CardTitle>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={byStore.map(s=>({ name:s.store, margin:+(+s.margin).toFixed(2) }))}>
              <CartesianGrid {...ax.grid}/>
              <XAxis dataKey="name" {...ax.xProps} tick={{ fontSize:13, fill:T.mu }}/>
              <YAxis {...ax.yProps} tickFormatter={v=>v+'%'}/>
              <Tooltip formatter={v=>fP(+v)}/>
              <Bar dataKey="margin" name="Margin" radius={[4,4,0,0]}>
                {byStore.map((s,i)=><Cell key={i} fill={(+s.margin)>=15?T.grn:(+s.margin)>=8?T.ora:T.red}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  );
}

/* ── LOGIN PAGE ───────────────────────────────────────── */
function LoginPage({ onLogin }) {
  const [email, setEmail] = useState('');
  const [pwd,   setPwd]   = useState('');
  const [loading, setLoading] = useState(false);
  const [err,   setErr]   = useState(null);

  const submit = async e => {
    e.preventDefault(); setLoading(true); setErr(null);
    try {
      const data = await authLogin(email, pwd);
      setToken(data.token); onLogin(data.user);
    } catch (e) { setErr(e.message); } finally { setLoading(false); }
  };

  return (
    <div style={{ minHeight:'100vh', display:'flex', alignItems:'center', justifyContent:'center', background:T.bg }}>
      <div style={{ ...S.card, padding:'40px 44px', width:380, boxShadow:`0 8px 32px ${T.shadow}` }}>
        <div style={{ marginBottom:28 }}>
          <div style={{ fontSize:24, fontWeight:800, color:T.tx, marginBottom:4 }}>FLW Analytics</div>
          <div style={{ fontSize:13.5, color:T.mu }}>Shopify Dashboard</div>
        </div>
        {err && <div style={{ background:T.redb, color:T.redtx, padding:'9px 13px', borderRadius:7, marginBottom:16, fontSize:13 }}>{err}</div>}
        <form onSubmit={submit}>
          <div style={{ marginBottom:14 }}>
            <label style={{ display:'block', fontSize:13, fontWeight:600, color:T.tx2, marginBottom:6 }}>Email</label>
            <input type="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="admin@flw.com"
              style={{ ...S.inp, width:'100%', padding:'9px 12px', fontSize:14 }}/>
          </div>
          <div style={{ marginBottom:22 }}>
            <label style={{ display:'block', fontSize:13, fontWeight:600, color:T.tx2, marginBottom:6 }}>Password</label>
            <input type="password" value={pwd} onChange={e=>setPwd(e.target.value)} placeholder="••••••••"
              style={{ ...S.inp, width:'100%', padding:'9px 12px', fontSize:14 }}/>
          </div>
          <button type="submit" disabled={loading}
            style={{ ...S.btn, width:'100%', padding:11, fontSize:14.5, fontWeight:600, opacity:loading?.7:1 }}>
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}

/* ── NAVIGATION ───────────────────────────────────────── */
const NAV = [
  { group:'Overview', items:[{ id:'exec', label:'Executive Overview' }, { id:'daily', label:'Daily Performance' }] },
  { group:'Sales',    items:[{ id:'orders', label:'Orders' }, { id:'prods', label:'Products' }, { id:'prodrpt', label:'Product Report' }, { id:'platform', label:'Platform Report' }, { id:'shopcomp', label:'Shop Comparison' }] },
  { group:'Ads',      items:[{ id:'fbads', label:'Facebook Ads' }, { id:'gads', label:'Google Ads' }] },
  { group:'Analytics',items:[{ id:'profit', label:'Profit Analytics' }, { id:'cust', label:'Customers' }, { id:'ref', label:'Refunds & Coupons' }] },
  { group:'Operations',items:[{ id:'ops', label:'Operations' }] },
];
const PAGE_TITLES = {
  exec:'Executive Overview', daily:'Daily Performance', orders:'Orders',
  prods:'Products', prodrpt:'Product Report', shopcomp:'Shop Comparison',
  platform:'Platform Report', fbads:'Facebook Ads', gads:'Google Ads',
  profit:'Profit Analytics', cust:'Customers', ref:'Refunds & Coupons', ops:'Operations',
};

/* ── APP ROOT ─────────────────────────────────────────── */
export default function App() {
  const [user,       setUser]       = useState(null);
  const [initLoading,setInitLoading]= useState(true);
  const [page,       setPage]       = useState('exec');
  const [sbOpen,     setSbOpen]     = useState(true);
  const [websites,   setWebsites]   = useState([]);
  const [websiteId,  setWebsiteId]  = useState('all');
  const [latestDate, setLatestDate] = useState(null);
  const [dates,      setDates]      = useState({ start:'', end:'' });
  const [compare,    setCompare]    = useState('prev_period');

  useEffect(() => {
    const style = document.createElement('style');
    style.textContent = `@keyframes spin{to{transform:rotate(360deg)}}
      body{background:${T.bg};color:${T.tx};font-size:13px;}
      *{box-sizing:border-box;}
      select,input,button{font-family:inherit;}`;
    document.head.appendChild(style);

    // AUTH TEMPORARILY DISABLED — skip token check
    setUser({ id:1, email:'admin@flw.com', name:'Admin', role:'admin' });
    setInitLoading(false);
  }, []);

  useEffect(() => {
    if (!user) return;
    api('/websites').then(setWebsites).catch(()=>{});
    api('/latest-date', { website_id:websiteId }).then(d => {
      const latest = d.latest || new Date().toISOString().slice(0,10);
      setLatestDate(latest);
      const start = new Date(latest+'T12:00:00');
      start.setDate(start.getDate()-29);
      setDates({ start:start.toISOString().slice(0,10), end:latest });
    }).catch(()=>{});
  }, [user, websiteId]);

  if (initLoading) return <div style={{ minHeight:'100vh', background:T.bg, display:'flex', alignItems:'center', justifyContent:'center' }}>Loading...</div>;
  if (!user) return <LoginPage onLogin={u=>setUser(u)}/>;

  const PAGES = { exec:ExecPage, daily:DailyPage, orders:OrdersPage, prods:ProductsPage,
    prodrpt:ProductReportPage, shopcomp:ShopCompPage, platform:PlatformPage,
    fbads:FbAdsPage, gads:GAdsPage, profit:ProfitPage, cust:CustomersPage,
    ref:RefundsPage, ops:OpsPage };
  const PageComp = PAGES[page] || ExecPage;
  const pageProps = { dates, compare, websiteId, latestDate, websites };

  return (
    <div style={{ display:'flex', height:'100vh', background:T.bg, fontFamily:"'Segoe UI',system-ui,sans-serif", fontSize:13 }}>
      {/* Sidebar */}
      <aside style={{ width:sbOpen?220:52, background:T.sb, display:'flex', flexDirection:'column',
        flexShrink:0, transition:'width .2s', overflow:'hidden', minHeight:'100vh' }}>
        <div style={{ padding:'16px 14px 12px', borderBottom:`1px solid ${T.sba}`, display:'flex', alignItems:'center', gap:8, minWidth:220 }}>
          {sbOpen && <div>
            <div style={{ color:T.sbat, fontSize:14.5, fontWeight:700, letterSpacing:'-.3px' }}>FLW Analytics</div>
            <div style={{ color:T.sbt, fontSize:11, marginTop:1 }}>Shopify Dashboard</div>
          </div>}
          <button onClick={()=>setSbOpen(v=>!v)}
            style={{ marginLeft:sbOpen?'auto':0, background:'none', border:'none', color:T.sbt, cursor:'pointer', fontSize:18, padding:4, flexShrink:0 }}>
            ☰
          </button>
        </div>
        <nav style={{ flex:1, padding:4, overflowY:'auto', overflowX:'hidden' }}>
          {NAV.map(sec => (
            <div key={sec.group}>
              {sbOpen && <div style={{ fontSize:9.5, fontWeight:700, color:T.sbt, letterSpacing:'1.4px', textTransform:'uppercase', padding:'10px 12px 4px' }}>{sec.group}</div>}
              {!sbOpen && <div style={{ height:8 }}/>}
              {sec.items.map(item => (
                <button key={item.id} onClick={()=>setPage(item.id)} title={!sbOpen?item.label:undefined}
                  style={{ width:'calc(100% - 8px)', margin:'1px 4px', display:'flex', alignItems:'center',
                    gap:sbOpen?8:0, padding:sbOpen?'8px 12px':'9px 0',
                    justifyContent:sbOpen?'flex-start':'center', borderRadius:7,
                    border:'none', cursor:'pointer', background:page===item.id?T.sba:'transparent',
                    color:page===item.id?T.sbat:T.sbt, fontSize:13, fontFamily:'inherit',
                    textAlign:'left', fontWeight:page===item.id?600:400 }}>
                  <span style={{ width:5, height:5, borderRadius:'50%', flexShrink:0, display:'block',
                    background:page===item.id?T.pri:T.sbt }}/>
                  {sbOpen && item.label}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div style={{ padding:'10px 8px', borderTop:`1px solid ${T.sba}`, flexShrink:0 }}>
          {sbOpen ? (
            <>
              <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:8 }}>
                <div style={{ width:28, height:28, borderRadius:7, background:T.pri, display:'flex',
                  alignItems:'center', justifyContent:'center', fontSize:12, fontWeight:700, color:'#fff', flexShrink:0 }}>
                  {(user.name||'A').charAt(0).toUpperCase()}
                </div>
                <div>
                  <div style={{ fontSize:12.5, fontWeight:600, color:T.sbat }}>{user.name||user.email}</div>
                  <div style={{ fontSize:11, color:T.sbt }}>{user.role}</div>
                </div>
              </div>
              <button onClick={()=>{ clearAuth(); setUser(null); }}
                style={{ width:'100%', padding:'5px 0', background:T.sbh, border:`1px solid ${T.sba}`,
                  borderRadius:6, color:T.sbt, fontSize:12, cursor:'pointer', fontFamily:'inherit' }}>
                Logout
              </button>
            </>
          ) : (
            <button onClick={()=>{ clearAuth(); setUser(null); }} title="Logout"
              style={{ width:'100%', padding:'6px 0', background:T.sbh, border:`1px solid ${T.sba}`,
                borderRadius:6, color:T.sbt, cursor:'pointer', fontSize:16 }}>
              ↩
            </button>
          )}
        </div>
      </aside>

      {/* Main */}
      <div style={{ flex:1, display:'flex', flexDirection:'column', overflow:'hidden' }}>
        {/* Top bar with page title */}
        <div style={{ background:T.card, borderBottom:`1px solid ${T.bdr}`, padding:'11px 20px',
          display:'flex', alignItems:'center', gap:8, flexShrink:0 }}>
          <h1 style={{ fontSize:16, fontWeight:700, color:T.tx, margin:0, letterSpacing:'-.3px', flex:1 }}>
            {PAGE_TITLES[page]}
            {latestDate && <span style={{ fontSize:12, color:T.mu, marginLeft:10, fontWeight:400 }}>Latest data: {latestDate}</span>}
          </h1>
        </div>

        {/* Date filter bar (shown on all pages except Daily which has its own) */}
        {page !== 'daily' && (
          <DateFilter
            latestDate={latestDate}
            dates={dates}
            onChange={setDates}
            compare={compare}
            onCompare={setCompare}
            websites={websites}
            websiteId={websiteId}
            onWebsite={setWebsiteId}
          />
        )}

        {/* Page content */}
        <div style={{ flex:1, overflowY:'auto', padding:'16px 20px' }}>
          <PageComp {...pageProps}/>
        </div>
      </div>
    </div>
  );
}
