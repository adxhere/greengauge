import { DEMO } from '../api.js';
import { clock } from '../format.js';

export function AlertCard({ a }) {
  const cls = a.severity === 'alarm' ? 'alarm' : 'warning';
  const kind = { air_leak: 'Air leak', idle_running: a.values?.when === 'after_hours' ? 'After hours' : 'Idle running',
    power_factor: 'Power factor', max_demand: 'Max demand', motor_health: 'Motor health' }[a.category] || a.category;
  const since = a.since && a.since.length > 10 ? `since ${clock(a.since)}` : 'today';
  return (
    <div className={`alert ${cls}`}>
      <div className="alert-top"><span>{a.severity} · {kind}</span><span className="muted">{since}</span></div>
      <div className="alert-title">{a.title}</div>
      <div className="alert-msg">{a.message}</div>
    </div>
  );
}

export function Skeleton({ h = 160 }) {
  return <div className="skeleton" style={{ minHeight: h }} aria-hidden="true" />;
}

export function ErrorStrip({ error }) {
  if (!error) return null;
  return <div className="error-strip" role="alert">Couldn't refresh: {error.message}. Showing the last data received.</div>;
}

export function LivePill({ time, stale }) {
  return (
    <div className="live-pill">
      <span className={`live-dot${stale || DEMO ? ' stale' : ''}`} />
      {DEMO ? `SNAPSHOT · ${time ? clock(time) : '--:--'} IST` : stale ? 'RECONNECTING' : `LIVE · ${time ? clock(time) : '--:--'} IST`}
    </div>
  );
}
