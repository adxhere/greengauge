import { useEffect, useMemo, useState } from 'react';
import { usePoll } from '../api.js';
import { ErrorStrip, Skeleton } from '../components/ui.jsx';
import { CATEGORY, inr, money } from '../format.js';

export default function Fixes({ days }) {
  const { data: recs, error } = usePoll(`/api/recommendations?days=${days}`, 30000);
  const [off, setOff] = useState(null);
  const [copied, setCopied] = useState(false);

  // default plan: everything except slow paybacks (over a year)
  useEffect(() => {
    if (recs && off === null) {
      const o = {};
      recs.forEach((r) => { if (r.payback_months !== null && r.payback_months > 12) o[r.id] = true; });
      setOff(o);
    }
  }, [recs, off]);

  const plan = useMemo(() => {
    if (!recs) return null;
    const sel = recs.filter((r) => !(off || {})[r.id]);
    const money_ = sel.filter((r) => !r.savings_kind);
    const capex = sel.reduce((a, r) => a + r.capex_inr, 0);
    const save = money_.reduce((a, r) => a + r.savings_inr_per_year, 0);
    const kwh = money_.reduce((a, r) => a + (r.savings_kwh_per_year || 0), 0);
    const co2 = money_.reduce((a, r) => a + (r.co2_t_per_year || 0), 0);
    const risk = sel.filter((r) => r.savings_kind).reduce((a, r) => a + r.savings_inr_per_year, 0);
    const maxSave = recs.filter((r) => !r.savings_kind).reduce((a, r) => a + r.savings_inr_per_year, 0);
    return { sel, capex, save, kwh, co2, risk, share: maxSave ? save / maxSave : 0, payback: save > 0 ? (capex / save) * 12 : null };
  }, [recs, off]);

  if (!recs) return <><Skeleton h={80} /><Skeleton h={600} /></>;

  const toggle = (id) => setOff((o) => ({ ...(o || {}), [id]: !(o || {})[id] }));
  const quickWins = () => {
    const o = {};
    recs.forEach((r) => { if (r.payback_months === null || r.payback_months > 3) o[r.id] = true; });
    setOff(o);
  };
  const copyPlan = async () => {
    const lines = [
      'GreenGauge fix plan',
      ...plan.sel.map((r) => `- ${r.title}: cost ${inr(r.capex_inr)}, ${r.savings_kind ? `avoids ${money(r.savings_inr_per_year)} breakdown risk` : `saves ${money(r.savings_inr_per_year)}/yr`}`),
      `Total cost ${inr(plan.capex)} · saves ${money(plan.save)}/yr${plan.payback !== null ? ` · pays back in ${plan.payback.toFixed(1)} months` : ''}`,
    ];
    try { await navigator.clipboard.writeText(lines.join('\n')); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { /* clipboard blocked */ }
  };

  return (
    <>
      <header className="page-head">
        <div>
          <div className="kicker">{recs.length} fixes found · ranked by payback</div>
          <h1 className="page-title">What to fix first.</h1>
        </div>
        <div className="head-actions">
          <button type="button" className="btn" onClick={quickWins}>Quick wins only</button>
          <button type="button" className="btn" onClick={() => setOff({})}>Select all</button>
        </div>
      </header>
      <ErrorStrip error={error} />

      {recs.length === 0 ? <div className="empty-ok">Nothing to fix in this period. The plant is running clean.</div> : (
        <div className="grid plan-layout">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {recs.map((r) => <FixRow key={r.id} r={r} checked={!(off || {})[r.id]} onToggle={() => toggle(r.id)} />)}
          </div>
          <aside className="card plan" aria-label="Your plan">
            <div className="card-head">
              <h2 className="card-title">Your plan</h2>
              <span className="mono muted" style={{ fontSize: 11 }}>{plan.sel.length} OF {recs.length} FIXES</span>
            </div>
            <div className="plan-big">
              <div className="label" style={{ color: 'var(--green-ink)', fontWeight: 600 }}>Saves every year</div>
              <div className="v">{money(plan.save)}</div>
              <div style={{ fontSize: 14, fontWeight: 600, marginTop: 4 }}>
                {plan.payback !== null ? `pays back in ${plan.payback.toFixed(1)} months` : 'select a fix to see payback'}
              </div>
            </div>
            <div className="plan-rows">
              <div><span>Total cost</span><span>{inr(plan.capex)}</span></div>
              <div><span>Electricity saved</span><span>{Math.round(plan.kwh).toLocaleString('en-IN')} kWh/yr</span></div>
              <div><span>CO₂ avoided</span><span>{plan.co2.toFixed(1)} t/yr</span></div>
              <div><span>Breakdown risk covered</span><span>{plan.risk ? money(plan.risk) : '—'}</span></div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="bar-track" style={{ height: 10 }}><div className="bar-fill" style={{ height: 10, width: `${Math.round(plan.share * 100)}%` }} /></div>
              <div className="card-note small">{Math.round(plan.share * 100)}% of the savings GreenGauge found</div>
            </div>
            <button type="button" className="btn solid" onClick={copyPlan} aria-live="polite">{copied ? 'Copied to clipboard' : 'Copy plan to share'}</button>
            <p className="card-note small">Annualised from the metered data in this period. Costs are estimates: get vendor quotes before committing.</p>
          </aside>
        </div>
      )}
    </>
  );
}

function FixRow({ r, checked, onToggle }) {
  const risk = !!r.savings_kind;
  let chipCls = 'neutral', chip = r.payback_months !== null ? `${r.payback_months} mo` : 'Risk';
  if (risk) chipCls = 'alarm';
  else if (r.payback_months <= 3) chipCls = 'ok';
  else if (r.payback_months > 12) chipCls = 'warn';
  return (
    <div className={`fix-row${checked ? '' : ' unchecked'}`}>
      <input type="checkbox" id={`fix-${r.id}`} checked={checked} onChange={onToggle} />
      <label htmlFor={`fix-${r.id}`}>
        <span className="cat">{CATEGORY[r.category] || r.category}</span>
        <span className="title">{r.title}</span>
        <span className="finding">{r.finding}</span>
      </label>
      <div className="num"><div className="label" style={{ fontSize: 10 }}>Cost</div><div className="v">{inr(r.capex_inr)}</div></div>
      <div className="num">
        <div className="label" style={{ fontSize: 10 }}>{risk ? 'Avoids' : 'Saves / yr'}</div>
        <div className={`v ${risk ? 'alarm' : 'green'}`} style={{ fontWeight: 700 }}>{money(r.savings_inr_per_year)}{risk ? ' loss' : ''}</div>
      </div>
      <span className={`chip ${chipCls}`}>{chip}</span>
    </div>
  );
}
