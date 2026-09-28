import { usePoll } from '../api.js';
import { Gauge, LineChart, MiniBars, Sparkline } from '../components/charts.jsx';
import { ErrorStrip, Skeleton } from '../components/ui.jsx';
import { dayLabel, longDate, machineName } from '../format.js';

export default function Health({ days }) {
  const power = usePoll(`/api/power?days=${days}`, 30000);
  const leaks = usePoll(`/api/leaks?days=${days}`, 30000);
  const motors = usePoll(`/api/motors?days=${days}`, 30000);
  const recs = usePoll(`/api/recommendations?days=${days}`, 60000);

  return (
    <>
      <header className="page-head">
        <div>
          <div className="kicker">Power quality · compressed air · motors</div>
          <h1 className="page-title">Catch it before the bill does.</h1>
        </div>
      </header>
      <ErrorStrip error={power.error || leaks.error || motors.error} />
      <section className="grid wide-left">
        {power.data ? <PowerFactor p={power.data} apfcRec={(recs.data || []).find((r) => r.id === 'repair_apfc')} /> : <Skeleton h={380} />}
        {power.data ? <Demand p={power.data} /> : <Skeleton h={380} />}
      </section>
      <section className="grid wide-right">
        {leaks.data ? <Leaks l={leaks.data} /> : <Skeleton h={360} />}
        {motors.data ? <Motors m={motors.data} /> : <Skeleton h={360} />}
      </section>
    </>
  );
}

function PowerFactor({ p, apfcRec }) {
  const daily = p.pf_daily.filter((d) => d.pf !== null);
  const warn = 0.95, thr = p.pf_threshold;
  const lo = Math.min(0.86, ...daily.map((d) => d.pf - 0.03));
  const suspected = p.apfc.status === 'suspected_failure';
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2 className="card-title">Power factor</h2>
          <div className="card-sub">Daily, during production</div>
        </div>
        <span className={`chip ${suspected ? 'warn' : 'ok'}`}>{suspected ? 'APFC suspected' : 'Healthy'}</span>
      </div>
      {daily.length > 0 ? (
        <LineChart
          data={daily.map((d) => ({ label: dayLabel(d.date), value: d.pf }))}
          refs={[{ value: warn, color: '#FFC266' }, { value: thr, color: '#FF9A70', label: `PENALTY BELOW ${thr.toFixed(2)}` }]}
          domain={[lo, 1.0]}
          badFrom={(v) => v < warn}
          ariaLabel={`Daily power factor: ${daily.map((d) => `${d.date} ${d.pf}`).join(', ')}`}
        />
      ) : <p className="card-note">Not enough production data yet.</p>}
      <p className="card-note">
        {suspected
          ? <>Dropped on {longDate(p.apfc.since + 'T12:00:00+05:30')}: about <span className="amber" style={{ fontWeight: 600 }}>{p.apfc.kvar_shortfall} kVAR of capacitor steps</span> stopped working in the APFC panel.{apfcRec ? ` Fix costs ₹${apfcRec.capex_inr.toLocaleString('en-IN')}${apfcRec.payback_months !== null ? ` and pays back in ${apfcRec.payback_months} months` : ''}.` : ''}</>
          : `Power factor ${p.pf?.toFixed(3) ?? '—'} over this period. The capacitor panel is keeping up.`}
      </p>
    </div>
  );
}

function Demand({ p }) {
  const blocks = p.demand_exceeded_blocks.length;
  return (
    <div className="card">
      <h2 className="card-title">Maximum demand</h2>
      <div className="card-sub" style={{ marginTop: -6 }}>Highest 30-minute average this period</div>
      <Gauge value={p.max_demand_kva} limit={p.contract_demand_kva} ariaLabel={`Maximum demand ${p.max_demand_kva} kVA against a ${p.contract_demand_kva} kVA contract`} />
      <div className="grid cols-2" style={{ gap: 10 }}>
        <div className={`stat-box${blocks ? ' alarm' : ''}`}>
          <div className={`v${blocks ? ' alarm' : ''}`}>{blocks}</div>
          <div className="card-note small soft">half-hours over contract</div>
        </div>
        <div className="stat-box">
          <div className="v">{p.excess_kva > 0 ? `+${p.excess_kva}` : `${Math.round(p.contract_demand_kva - p.max_demand_kva)}`}</div>
          <div className="card-note small soft">{p.excess_kva > 0 ? 'kVA above the limit' : 'kVA of headroom'}</div>
        </div>
      </div>
      <p className="card-note small">
        {p.excess_kva > 0 && p.apfc.status === 'suspected_failure' ? 'The low power factor pushed kVA up. Repairing the APFC fixes both.'
          : p.excess_kva > 0 ? 'Stagger large loads at shift start to stay under the contract.' : 'Demand stayed inside the contract.'}
      </p>
    </div>
  );
}

function Leaks({ l }) {
  if (l.status === 'insufficient_data' || l.status === 'no_compressor') {
    return (
      <div className="card">
        <h2 className="card-title">Air leak test</h2>
        <p className="card-note">Waiting for enough break-time or after-hours data to run the test ({l.sample_minutes || 0} of 20 minutes so far).</p>
      </div>
    );
  }
  const cls = l.status === 'alarm' ? 'alarm' : l.status === 'warning' ? 'warn' : 'ok';
  return (
    <div className="card">
      <div className="card-head">
        <h2 className="card-title">Air leak test</h2>
        <span className={`chip ${cls}`}>{l.status}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <span className={`big ${l.status === 'ok' ? 'green' : 'alarm'}`} style={{ fontSize: 44 }}>{Math.round(l.leak_pct)}%</span>
        <span className="soft" style={{ fontSize: 14 }}>of compressor output leaks</span>
      </div>
      {l.daily.length > 0 && (
        <MiniBars data={l.daily.slice(-7).map((d) => ({ label: dayLabel(d.date).split(' ')[0], value: d.leak_pct }))} target={l.target_pct}
          ariaLabel={`Daily leak percentage: ${l.daily.map((d) => d.leak_pct).join(', ')}`} />
      )}
      <p className="card-note small">No-demand test: time the compressor spends loaded while nothing uses air, during breaks and after hours.</p>
    </div>
  );
}

function Motors({ m }) {
  return (
    <div className="card">
      <div className="card-head">
        <h2 className="card-title">Motor health</h2>
        <span className="mono muted" style={{ fontSize: 11 }}>CURRENT IMBALANCE · WARN {m.warn_pct}% · ALARM {m.alarm_pct}%</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {m.machines.map((x) => {
          const bad = x.status === 'warning' || x.status === 'alarm' || x.status === 'watch';
          const chip = { alarm: 'alarm', warning: 'warn', watch: 'warn', ok: 'ok' }[x.status];
          const trend = x.trend_pct_per_day;
          return (
            <div key={x.device} className={`motor-row${x.status === 'alarm' ? ' alarm' : bad ? ' flagged' : ''}`}>
              <div>
                <div style={{ fontSize: bad ? 15 : 14.5, fontWeight: bad ? 700 : 600 }}>{machineName(x.device)}</div>
                {x.days_to_alarm !== null && <div className="amber" style={{ fontSize: 12.5 }}>Alarm level in about {Math.max(1, Math.round(x.days_to_alarm))} day{Math.round(x.days_to_alarm) === 1 ? '' : 's'}</div>}
              </div>
              <div className={bad ? 'amber' : 'mono'} style={bad ? { fontFamily: 'var(--display)', fontSize: 18, fontWeight: 700 } : { fontSize: 13 }}>{x.imbalance_pct.toFixed(2)}%</div>
              <div className={`mono ${bad ? 'amber' : 'muted'}`} style={{ fontSize: 12 }}>{trend !== null && Math.abs(trend) >= 0.1 ? `${trend > 0 ? '+' : ''}${trend.toFixed(2)} / DAY` : 'STEADY'}</div>
              <Sparkline values={x.daily.map((d) => d.imbalance_pct)} alarm={bad ? m.alarm_pct : null} color={bad ? '#FFB547' : '#3DCD58'} />
              <span className={`chip ${chip}`}>{x.status}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
