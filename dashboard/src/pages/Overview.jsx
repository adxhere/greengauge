import { usePoll } from '../api.js';
import { BarChart } from '../components/charts.jsx';
import { AlertCard, ErrorStrip, LivePill, Skeleton } from '../components/ui.jsx';
import { CATEGORY, dayLabel, dateRange, inr, longDate, machineName, money, num } from '../format.js';

const PERIODS = [{ days: 1, label: '24H' }, { days: 7, label: '7D' }, { days: 30, label: '30D' }];

export default function Overview({ days, setDays }) {
  const summary = usePoll(`/api/summary?days=${days}`, 15000);
  const overview = usePoll(`/api/overview?days=${days}`, 30000);
  const baseline = usePoll(`/api/baseline?days=${days}`, 60000);
  const power = usePoll(`/api/power?days=${days}`, 30000);
  const idle = usePoll(`/api/idle?days=${days}`, 30000);
  const leaks = usePoll(`/api/leaks?days=${days}`, 30000);

  const s = summary.data;
  const period = s?.period;

  return (
    <>
      <header className="page-head">
        <div>
          <div className="kicker">{period ? dateRange(period.start, period.end) : 'Loading…'}</div>
          <h1 className="page-title">Every casting, costed.</h1>
        </div>
        <div className="head-actions">
          <LivePill time={period?.end} stale={!!summary.error} />
          <div className="segmented" role="group" aria-label="Period">
            {PERIODS.map((p) => (
              <button key={p.days} type="button" aria-pressed={days === p.days} onClick={() => setDays(p.days)}>{p.label}</button>
            ))}
          </div>
        </div>
      </header>
      <ErrorStrip error={summary.error} />

      {!s ? <Skeleton h={150} /> : <KpiRow s={s} power={power.data} />}

      <section className="grid wide-left">
        {overview.data ? <EnergyCard ov={overview.data} base={baseline.data} idle={idle.data} /> : <Skeleton h={380} />}
        {s ? <AlertsCard alerts={s.alerts} /> : <Skeleton h={380} />}
      </section>

      <section className="grid wide-left">
        {s ? <TopFixes recs={s.top_recommendations} /> : <Skeleton h={240} />}
        {overview.data ? <Breakdown ov={overview.data} idle={idle.data} leaks={leaks.data} /> : <Skeleton h={240} />}
      </section>
    </>
  );
}

function KpiRow({ s, power }) {
  const t = s.totals, w = s.waste, o = s.opportunity;
  const wasted = (w.idle_cost_inr || 0) + (w.leak_cost_inr || 0);
  const payback = o.savings_inr_per_year > 0 ? (o.capex_inr / o.savings_inr_per_year) * 12 : null;
  const daily = power?.pf_daily || [];
  const today = daily.length ? daily[daily.length - 1].pf : t.pf;
  const good = daily.filter((d) => d.pf >= 0.97);
  const dropped = good.length && today < 0.95;
  const apfc = power?.apfc;
  return (
    <section className="grid cols-4" aria-label="Key numbers">
      <div className="card">
        <div className="label">Cost per casting</div>
        <div className="big">{t.cost_per_piece_inr !== null ? `₹${num(t.cost_per_piece_inr, 2)}` : '—'}</div>
        <div className="sub">{num(t.kwh_per_piece, 2)} kWh · {num(t.kg_co2_per_piece, 2)} kg CO₂ each</div>
      </div>
      <div className={`card${wasted > 0 ? ' warn' : ''}`}>
        <div className={`label${wasted > 0 ? ' amber' : ''}`}>Wasted this period</div>
        <div className={`big${wasted > 0 ? ' amber' : ''}`}>{inr(wasted)}</div>
        <div className="sub">Idle machines {inr(w.idle_cost_inr)} · air leaks {inr(w.leak_cost_inr)}</div>
      </div>
      <div className="card hero-green">
        <div className="label">Savings on the table</div>
        <div className="big" style={{ fontWeight: 800 }}>{money(o.savings_inr_per_year)}<small>/yr</small></div>
        <div className="sub">{money(o.capex_inr)} of fixes{payback !== null ? ` · pays back in ${payback.toFixed(1)} months` : ''}</div>
      </div>
      <div className="card">
        <div className="label">Power factor{daily.length ? ' today' : ''}</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <span className="big">{today !== null && today !== undefined ? today.toFixed(2) : '—'}</span>
          {dropped ? <span className="mono amber" style={{ fontSize: 12 }}>▼ from {good[good.length - 1].pf.toFixed(2)}</span> : null}
        </div>
        <div className="sub">
          {apfc?.status === 'suspected_failure' ? `APFC panel suspected since ${longDate(apfc.since + 'T12:00:00+05:30')}` : 'Capacitor panel working normally'}
        </div>
      </div>
    </section>
  );
}

function EnergyCard({ ov, base, idle }) {
  const days = ov.daily;
  const withPieces = days.filter((d) => d.kwh_per_piece !== null);
  const worst = withPieces.reduce((a, d) => (!a || d.kwh_per_piece > a.kwh_per_piece ? d : a), null);
  const target = base?.status === 'ok' ? base.baseline_period.kwh_per_piece : null;
  const data = days.slice(-7).map((d) => ({
    label: dayLabel(d.date), value: d.kwh_per_piece,
    highlight: worst && d.date === worst.date && withPieces.length > 1,
  }));
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2 className="card-title">Energy per casting</h2>
          <div className="card-sub">kWh per casting, daily{target ? ' · dashed line is the baseline period' : ''}</div>
        </div>
      </div>
      <BarChart
        data={data}
        target={target}
        targetLabel={target ? `BASELINE ${target.toFixed(1)}` : undefined}
        ariaLabel={`Daily kWh per casting: ${data.map((d) => `${d.label} ${d.value ?? 'no production'}`).join(', ')}`}
      />
      {worst && withPieces.length > 1 && (
        <p className="card-note">
          Worst day: <span className="amber" style={{ fontWeight: 600 }}>{longDate(worst.date + 'T12:00:00+05:30')}, {worst.kwh_per_piece.toFixed(1)} kWh per casting</span>.
          {idle?.total_cost_inr > 0 ? ` Machines running with no production cost ${inr(idle.total_cost_inr)} over this period.` : ''}
        </p>
      )}
    </div>
  );
}

function AlertsCard({ alerts }) {
  return (
    <div className="card">
      <div className="card-head">
        <h2 className="card-title">Right now</h2>
        {alerts.length > 0 && <span className="chip alarm">{alerts.length} alert{alerts.length > 1 ? 's' : ''}</span>}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {alerts.length === 0 ? <div className="empty-ok">All clear. Nothing is being wasted right now.</div> : alerts.slice(0, 3).map((a) => <AlertCard key={a.id} a={a} />)}
      </div>
      <a className="card-link" href="#/live" style={{ marginTop: 'auto' }}>Open live plant →</a>
    </div>
  );
}

function TopFixes({ recs }) {
  return (
    <div className="card">
      <div className="card-head">
        <h2 className="card-title">Fix these first</h2>
        <a className="card-link" href="#/fixes">All fixes →</a>
      </div>
      {recs.length === 0 ? <div className="empty-ok">No fixes needed in this period.</div> : (
        <div className="grid cols-3" style={{ gap: 12 }}>
          {recs.map((r) => (
            <div className="fix-tile" key={r.id}>
              <div className="label">{CATEGORY[r.category] || r.category}</div>
              <div className="title">{r.title}</div>
              <div className="value">
                {r.savings_kind ? <span className="alarm">{money(r.savings_inr_per_year)}</span> : money(r.savings_inr_per_year)}
                <small>{r.savings_kind ? ' risk' : '/yr'}</small>
              </div>
              <div className="meta"><span>COST {inr(r.capex_inr)}</span><span className="green">{r.payback_months !== null ? `${r.payback_months} MO` : 'URGENT'}</span></div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Breakdown({ ov, idle, leaks }) {
  const byMachine = Object.entries(ov.kwh_by_machine).sort((a, b) => b[1] - a[1]);
  const total = byMachine.reduce((a, [, v]) => a + v, 0) || 1;
  const wasteful = new Set((idle?.by_machine || []).filter((m) => m.kwh > 0).map((m) => m.device));
  if (leaks && (leaks.status === 'alarm' || leaks.status === 'warning')) wasteful.add('air_compressor');
  return (
    <div className="card">
      <h2 className="card-title">Where the energy goes</h2>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        {byMachine.map(([dev, kwh]) => {
          const pct = (kwh / total) * 100;
          return (
            <div className="share-row" key={dev}>
              <span>{machineName(dev)}</span>
              <span className="share-track"><span className={`share-fill${wasteful.has(dev) ? ' waste' : ''}`} style={{ display: 'block', width: `${pct}%` }} /></span>
              <span className="pct">{pct >= 10 ? pct.toFixed(0) : pct.toFixed(1)}%</span>
            </div>
          );
        })}
      </div>
      {wasteful.size > 0 && <p className="card-note small">Amber = machines with waste found in this period.</p>}
    </div>
  );
}
