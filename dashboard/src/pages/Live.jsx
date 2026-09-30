import { DEMO, usePoll } from '../api.js';
import { LoadChart } from '../components/charts.jsx';
import { AlertCard, ErrorStrip, LivePill, Skeleton } from '../components/ui.jsx';
import { clock, duration, inr, longDate, machineName, num } from '../format.js';

export default function Live() {
  const live = usePoll('/api/live', 3000);
  const alerts = usePoll('/api/alerts', 5000);
  const series = usePoll('/api/timeseries?device=main_incomer&hours=24&bucket_minutes=15', 30000);

  const lv = live.data;
  if (!lv) return <><Skeleton h={80} /><Skeleton h={300} /><Skeleton h={340} /></>;

  const flagged = lv.machines.filter((m) => m.idle_flag);
  const wasteFrom = flagged.length ? flagged.map((m) => m.idle_flag.since).sort()[0] : null;
  const leakAlert = (alerts.data || []).find((a) => a.category === 'air_leak');
  const stateText = { production: `Shift ${lv.shift} · producing`, break: `Shift ${lv.shift} · break`, after_hours: 'After hours' }[lv.state];
  const title =
    lv.state === 'after_hours' ? (flagged.length ? 'The plant should be asleep.' : 'Quiet night. Nothing wasted.')
      : lv.state === 'break' ? (flagged.length ? 'Break time, but not for everyone.' : 'Break time. Machines resting.')
        : `Shift ${lv.shift} is running.`;

  return (
    <>
      <header className="page-head">
        <div>
          <div className={`kicker${flagged.length ? ' warn' : ''}`}>{longDate(lv.time)} · {clock(lv.time)} · {stateText}</div>
          <h1 className="page-title">{title}</h1>
        </div>
        <LivePill time={lv.time} stale={!!live.error} />
      </header>
      <ErrorStrip error={live.error} />

      <section className="grid two-one">
        <div className="card" style={{ gap: 16 }}>
          <div className="grid cols-3">
            <div>
              <div className="label">Drawing now</div>
              <div className="big" style={{ marginTop: 6 }}>{num(lv.kw)}<small className="muted"> kW</small></div>
            </div>
            {flagged.length > 0 ? (
              <>
                <div>
                  <div className="label">Should be</div>
                  <div className="big green" style={{ marginTop: 6 }}>≈{Math.round(lv.expected_kw)}<small className="muted"> kW</small></div>
                  <div className="sub">without the machines left running</div>
                </div>
                <div>
                  <div className="label amber">Doing nothing useful</div>
                  <div className="big amber" style={{ marginTop: 6 }}>{Math.round(lv.waste_kw)}<small> kW</small></div>
                  <div className="sub">≈{inr(lv.waste_inr_per_hour)} every hour at the current tariff</div>
                </div>
              </>
            ) : (
              <>
                <div>
                  <div className="label">Power factor</div>
                  <div className="big" style={{ marginTop: 6 }}>{lv.pf?.toFixed(2)}</div>
                </div>
                <div>
                  <div className="label">Demand</div>
                  <div className="big" style={{ marginTop: 6 }}>{Math.round(lv.kva)}<small className="muted"> kVA</small></div>
                  <div className="sub">of {lv.contract_demand_kva} kVA contract</div>
                </div>
              </>
            )}
          </div>
          {series.data?.points?.length > 1 && (
            <LoadChart points={series.data.points} expectedKw={flagged.length ? lv.expected_kw : null} wasteFrom={wasteFrom}
              ariaLabel="Plant load over the last 24 hours" />
          )}
        </div>

        <div className="card">
          <div className="card-head">
            <h2 className="card-title">Alerts</h2>
            <span className="mono muted" style={{ fontSize: 11 }}>{(alerts.data || []).length} ACTIVE</span>
          </div>
          {(alerts.data || []).length === 0 ? <div className="empty-ok">All clear right now.</div> : (
            <>
              <div className="bubble">
                <div className="from">Message to shift supervisor</div>
                <p>{alerts.data[0].message}</p>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {alerts.data.slice(1, 3).map((a) => <AlertCard key={a.id} a={a} />)}
              </div>
            </>
          )}
          <p className="card-note small">{DEMO ? 'Recorded snapshot of the live system. The full version updates every 3 seconds.' : 'New alerts also go to the supervisor on Telegram, in English and Tamil.'}</p>
        </div>
      </section>

      <section className="grid cols-4" aria-label="Machines">
        <IncomerCard lv={lv} />
        {lv.machines.map((m) => <MachineCard key={m.device} m={m} leak={m.device === 'air_compressor' ? leakAlert : null} state={lv.state} />)}
      </section>
    </>
  );
}

function IncomerCard({ lv }) {
  const pct = Math.min((lv.kva / lv.contract_demand_kva) * 100, 100);
  const over = lv.kva > lv.contract_demand_kva;
  return (
    <div className="machine">
      <div className="top"><span className="name">Main incomer</span><span className="mono muted" style={{ fontSize: 10 }}>PF {lv.pf?.toFixed(2)}</span></div>
      <div className="kw">{Math.round(lv.kva)}<small> kVA</small></div>
      <div className="bar-track"><div className={`bar-fill${over ? ' over' : ''}`} style={{ width: `${pct}%` }} /></div>
      <div className="mono muted" style={{ fontSize: 10 }}>OF {lv.contract_demand_kva} kVA CONTRACT</div>
    </div>
  );
}

function MachineCard({ m, leak, state }) {
  const f = m.idle_flag;
  const off = m.kw <= 0.5 && !f;
  const cls = f ? 'machine flagged' : off ? 'machine off' : 'machine';
  const chip = f ? <span className="chip warn">{f.state === 'after_hours' ? 'After hours' : 'Idle in break'}</span>
    : off ? <span className="chip off">Off</span>
      : <span className="chip ok">{m.status === 'idle' ? 'Idle' : 'Running'}</span>;
  let note;
  if (f) {
    const when = f.state === 'after_hours' ? 'after the shift' : 'through the break';
    note = `${leak ? 'Cycling on leaks with no air demand. ' : `Left on ${when}. `}${duration(f.minutes)} · ${inr(f.cost_inr)} so far.`;
  } else if (off) {
    note = state === 'production' ? 'Waiting for work.' : 'Off, as expected.';
  } else if (leak) {
    note = 'Running. Leak test shows air being lost.';
  } else {
    note = state === 'after_hours' ? 'Allowed to run after hours.' : 'Running normally.';
  }
  return (
    <div className={cls}>
      <div className="top"><span className="name">{machineName(m.device)}</span>{chip}</div>
      <div className="kw">{num(m.kw)}<small> kW</small></div>
      <div className="note">{note}</div>
    </div>
  );
}
