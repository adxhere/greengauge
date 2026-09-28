// Hand-drawn SVG charts, styled to match the GreenGauge design (no chart library).

const C = { grid: '#1E2A22', text: '#93A69A', ink: '#EAF2EC', green: '#3DCD58', bar: '#2B5C37', amber: '#FFB547', amberText: '#FFC266', alarm: '#FF9A70' };

function niceDomain(values, pad = 1) {
  const v = values.filter((x) => x !== null && x !== undefined);
  if (!v.length) return [0, 1];
  let lo = Math.floor(Math.min(...v) - pad), hi = Math.ceil(Math.max(...v) + pad);
  if (lo === hi) hi = lo + 1;
  return [lo, hi];
}

// Daily bars with an optional dashed target line. data: [{label, value, highlight}]
export function BarChart({ data, target, targetLabel, format = (v) => v.toFixed(1), ariaLabel, light = false }) {
  const W = 640, H = 232, L = 44, R = 630, T = 22, B = 190;
  const [lo, hi] = niceDomain([...data.map((d) => d.value), target], 1.2);
  const y = (v) => B - ((v - lo) / (hi - lo)) * (B - T);
  const slot = (R - L) / Math.max(data.length, 1);
  const bw = Math.min(44, slot * 0.55);
  const ticks = [];
  for (let t = Math.ceil(lo); t <= hi; t += Math.max(1, Math.round((hi - lo) / 4))) ticks.push(t);
  const ink = light ? '#0D1A11' : C.ink, sub = light ? '#4E6154' : C.text, grid = light ? '#D5DDD6' : C.grid;
  const fill = light ? '#177A32' : C.bar, hl = light ? '#B86E00' : C.amber;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }} role="img" aria-label={ariaLabel}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={L} y1={y(t)} x2={R} y2={y(t)} stroke={grid} />
          <text x="0" y={y(t) + 4} fontSize="11" fill={sub}>{t}</text>
        </g>
      ))}
      {data.map((d, i) => {
        const cx = L + slot * (i + 0.5);
        if (d.value === null || d.value === undefined) {
          return (
            <g key={i}>
              <rect x={cx - bw / 2} y={B - 4} width={bw} height="4" rx="2" fill={grid} />
              <text x={cx} y={B - 12} fontSize="12" fill={sub} textAnchor="middle">—</text>
              <text x={cx} y={H - 20} fontSize="11" fill={sub} textAnchor="middle">{d.label}</text>
            </g>
          );
        }
        const top = y(d.value);
        return (
          <g key={i}>
            <rect x={cx - bw / 2} y={top} width={bw} height={Math.max(B - top, 2)} rx="8" fill={d.highlight ? hl : fill} />
            <text x={cx} y={top - 8} fontSize="12" fontWeight="600" fill={d.highlight ? (light ? hl : C.amberText) : ink} textAnchor="middle">{format(d.value)}</text>
            <text x={cx} y={H - 20} fontSize="11" fill={d.highlight ? (light ? hl : C.amberText) : sub} textAnchor="middle">{d.label}</text>
          </g>
        );
      })}
      {target !== undefined && target !== null && (
        <g>
          <line x1={L} y1={y(target)} x2={R} y2={y(target)} stroke={light ? '#177A32' : C.green} strokeWidth="2" strokeDasharray="6 6" />
          {targetLabel && <text x={R} y={y(target) - 6} fontSize="11" fill={light ? '#177A32' : C.green} textAnchor="end">{targetLabel}</text>}
        </g>
      )}
    </svg>
  );
}

// Daily line with reference lines. data: [{label, value}], refs: [{value, color, label}]
export function LineChart({ data, refs = [], domain, badFrom, format = (v) => v.toFixed(2), ariaLabel }) {
  const W = 660, H = 230, L = 50, R = 620, T = 16, B = 196;
  const [lo, hi] = domain;
  const y = (v) => T + ((hi - v) / (hi - lo)) * (B - T);
  const x = (i) => (data.length > 1 ? L + (i * (R - L)) / (data.length - 1) : (L + R) / 2);
  const pts = data.map((d, i) => [x(i), y(d.value)]);
  const path = (arr) => arr.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
  const firstBad = data.findIndex((d) => badFrom(d.value));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }} role="img" aria-label={ariaLabel}>
      <line x1={L} y1={y(hi)} x2={R + 20} y2={y(hi)} stroke={C.grid} />
      <text x="0" y={y(hi) + 4} fontSize="11" fill={C.text}>{hi.toFixed(2)}</text>
      {refs.map((r) => (
        <g key={r.value}>
          <line x1={L} y1={y(r.value)} x2={R + 20} y2={y(r.value)} stroke={r.color} strokeDasharray="5 5" />
          <text x="0" y={y(r.value) + 4} fontSize="11" fill={r.color}>{r.value.toFixed(2)}</text>
          {r.label && <text x={R + 20} y={y(r.value) + 16} fontSize="11" fill={r.color} textAnchor="end">{r.label}</text>}
        </g>
      ))}
      {pts.length > 1 && <path d={path(pts)} fill="none" stroke={C.green} strokeWidth="3" strokeLinejoin="round" />}
      {firstBad > 0 && <path d={path(pts.slice(firstBad - 1))} fill="none" stroke={C.amber} strokeWidth="3" strokeLinejoin="round" />}
      {pts.map((p, i) => {
        const bad = badFrom(data[i].value);
        return (
          <g key={i}>
            <circle cx={p[0]} cy={p[1]} r="5" fill="#0A0D0B" stroke={bad ? C.amber : C.green} strokeWidth="3" />
            {(i === 0 || i === firstBad || i === pts.length - 1) && (
              <text x={p[0]} y={p[1] - 12} fontSize="12" fontWeight="600" fill={bad ? C.amberText : C.ink} textAnchor="middle">{format(data[i].value)}</text>
            )}
            <text x={p[0]} y={H - 16} fontSize="11" fill={bad ? C.amberText : C.text} textAnchor="middle">{data[i].label}</text>
          </g>
        );
      })}
    </svg>
  );
}

// 24-hour load profile. points: [{time, kw}], wasteFrom: ISO time where waste started (optional)
export function LoadChart({ points, expectedKw, wasteFrom, ariaLabel }) {
  const W = 1000, H = 170, T = 10, B = 140;
  if (!points || points.length < 2) return null;
  const t0 = new Date(points[0].time).getTime(), t1 = new Date(points[points.length - 1].time).getTime();
  const maxKw = Math.max(...points.map((p) => p.kw || 0), 50) * 1.08;
  const x = (t) => ((new Date(t).getTime() - t0) / Math.max(t1 - t0, 1)) * W;
  const y = (v) => B - ((v || 0) / maxKw) * (B - T);
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(p.time).toFixed(1)} ${y(p.kw).toFixed(1)}`).join(' ');
  const area = `${line} L${W} ${B} L0 ${B} Z`;
  const wf = wasteFrom ? new Date(wasteFrom).getTime() : null;
  const wasteIdx = wf ? points.findIndex((p) => new Date(p.time).getTime() >= wf) : -1;
  const wastePts = wasteIdx > 0 ? points.slice(wasteIdx - 1) : [];
  const wasteLine = wastePts.map((p, i) => `${i ? 'L' : 'M'}${x(p.time).toFixed(1)} ${y(p.kw).toFixed(1)}`).join(' ');
  const hours = [];
  for (let t = Math.ceil(t0 / 21600000) * 21600000; t <= t1; t += 21600000) hours.push(t);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }} role="img" aria-label={ariaLabel}>
      {wastePts.length > 0 && <rect x={x(wastePts[0].time)} y={T} width={W - x(wastePts[0].time)} height={B - T} fill={C.amber} opacity="0.12" />}
      <path d={area} fill={C.green} opacity="0.14" />
      <path d={line} fill="none" stroke={C.green} strokeWidth="2.5" strokeLinejoin="round" />
      {wastePts.length > 1 && <path d={wasteLine} fill="none" stroke={C.amber} strokeWidth="3" strokeLinejoin="round" />}
      {expectedKw !== null && expectedKw !== undefined && wastePts.length > 0 && (
        <g>
          <line x1="0" y1={y(expectedKw)} x2={W} y2={y(expectedKw)} stroke={C.text} strokeDasharray="4 5" />
          <text x={x(wastePts[0].time) - 8} y={y(expectedKw) - 8} fontSize="12" fontWeight="600" fill={C.amberText} textAnchor="end">should be here</text>
        </g>
      )}
      {hours.map((t) => (
        <text key={t} x={Math.min(x(t), W - 40)} y={H - 6} fontSize="12" fill={C.text}>
          {new Date(t).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' })}
        </text>
      ))}
    </svg>
  );
}

// Semicircle gauge (maximum demand vs contract)
export function Gauge({ value, limit, unit = 'kVA', ariaLabel }) {
  const max = Math.max(limit * 1.12, value * 1.05);
  const cx = 130, cy = 130, r = 100;
  const pt = (v, rad = r) => {
    const a = Math.PI - (Math.min(v, max) / max) * Math.PI;
    return [cx + rad * Math.cos(a), cy - rad * Math.sin(a)];
  };
  const [vx, vy] = pt(value);
  const [i1, j1] = pt(limit, 82), [i2, j2] = pt(limit, 118);
  const over = value > limit;
  return (
    <svg viewBox="0 0 260 160" style={{ width: '100%', maxWidth: 300, height: 'auto', display: 'block', alignSelf: 'center' }} role="img" aria-label={ariaLabel}>
      <path d="M30 130 A100 100 0 0 1 230 130" fill="none" stroke={C.grid} strokeWidth="18" strokeLinecap="round" />
      <path d={`M30 130 A100 100 0 0 1 ${vx.toFixed(1)} ${vy.toFixed(1)}`} fill="none" stroke={over ? C.alarm : C.green} strokeWidth="18" strokeLinecap="round" />
      <line x1={i1} y1={j1} x2={i2} y2={j2} stroke={C.ink} strokeWidth="3" />
      <text x="130" y="112" textAnchor="middle" style={{ fontFamily: 'var(--display)' }} fontSize="38" fontWeight="700" fill={C.ink}>{Math.round(value)}</text>
      <text x="130" y="134" textAnchor="middle" fontSize="12" fill={C.text}>{unit} · CONTRACT {limit}</text>
    </svg>
  );
}

// Small bars for daily percentages with a target line
export function MiniBars({ data, target, max = 40, ariaLabel }) {
  const W = 300, B = 110, T = 10;
  const slot = W / Math.max(data.length, 1), bw = Math.min(30, slot * 0.6);
  const y = (v) => B - (Math.min(v, max) / max) * (B - T);
  return (
    <svg viewBox="0 0 300 130" style={{ width: '100%', height: 'auto', display: 'block' }} role="img" aria-label={ariaLabel}>
      {data.map((d, i) => (
        <g key={i}>
          <rect x={slot * (i + 0.5) - bw / 2} y={y(d.value)} width={bw} height={B - y(d.value)} rx="6" fill={d.value > target ? C.alarm : C.green} opacity="0.85" />
          <text x={slot * (i + 0.5)} y="126" fontSize="10.5" fill={C.text} textAnchor="middle">{d.label}</text>
        </g>
      ))}
      <line x1="0" y1={y(target)} x2={W} y2={y(target)} stroke={C.green} strokeWidth="2" strokeDasharray="5 5" />
      <text x={W - 4} y={y(target) - 5} fontSize="11" fill={C.green} textAnchor="end">TARGET {target}%</text>
    </svg>
  );
}

export function Sparkline({ values, alarm, max = 6, color }) {
  const W = 120, H = 32;
  if (!values || !values.length) return <svg width={W} height={H} aria-hidden="true" />;
  const y = (v) => H - (Math.min(v, max) / max) * H;
  const x = (i) => (values.length > 1 ? (i * W) / (values.length - 1) : W / 2);
  const d = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} aria-hidden="true">
      {alarm && <line x1="0" y1={y(alarm)} x2={W} y2={y(alarm)} stroke={C.alarm} strokeDasharray="3 3" />}
      <path d={values.length > 1 ? d : `M0 ${y(values[0])} L${W} ${y(values[0])}`} fill="none" stroke={color || C.green} strokeWidth="2.5" strokeLinejoin="round" />
    </svg>
  );
}
