import { usePoll } from '../api.js';
import { BarChart } from '../components/charts.jsx';
import { GaugeMark } from '../components/Sidebar.jsx';
import { ErrorStrip, Skeleton } from '../components/ui.jsx';
import { dateRange, dayLabel, num } from '../format.js';

function isoWeek(iso) {
  const d = new Date(iso);
  const t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return { year: t.getUTCFullYear(), week: Math.ceil(((t - yearStart) / 86400000 + 1) / 7) };
}

export default function Certificate({ days }) {
  const carbon = usePoll(`/api/carbon?days=${days}`, 60000);
  const recs = usePoll(`/api/recommendations?days=${days}`, 60000);
  const c = carbon.data;
  if (!c) return <Skeleton h={600} />;

  const initials = (c.plant || 'Plant').split(/\s+/).map((w) => w[0]).join('').toUpperCase();
  const { year, week } = isoWeek(c.period.end);
  const certId = `GG-${initials}-${year}-W${String(week).padStart(2, '0')}`;
  const lowCost = (recs.data || []).filter((r) => !r.savings_kind && r.payback_months !== null && r.payback_months <= 12);
  const avoidT = lowCost.reduce((a, r) => a + (r.co2_t_per_year || 0), 0);
  const avoidedInPeriod = avoidT * 1000 * (c.period.days / 365);
  const perPieceAfter = c.pieces ? (c.total_co2_kg - avoidedInPeriod) / c.pieces : null;
  const daily = c.daily.slice(-7);
  const worst = daily.filter((d) => d.kg_co2_per_piece !== null).reduce((a, d) => (!a || d.kg_co2_per_piece > a.kg_co2_per_piece ? d : a), null);

  return (
    <div className="cert-wrap">
      <ErrorStrip error={carbon.error} />
      <div className="no-print" style={{ alignSelf: 'stretch', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div className="kicker">Carbon certificate</div>
          <h1 className="page-title">A statement buyers can use.</h1>
        </div>
        <button type="button" className="btn solid" onClick={() => window.print()}>Print or save as PDF</button>
      </div>

      <article className="cert" aria-label="Product carbon statement">
        <div className="cert-band">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <GaugeMark size={30} />
            <span className="brand-name" style={{ fontSize: 17 }}>Green<span>Gauge</span></span>
          </div>
          <div className="mono" style={{ textAlign: 'right', fontSize: 11, letterSpacing: 1, lineHeight: 1.6 }}>
            <div className="green">PRODUCT CARBON STATEMENT</div>
            <div className="muted">NO. {certId}</div>
          </div>
        </div>
        <div className="cert-body">
          <div>
            <div className="kick">{c.product} · {dateRange(c.period.start, c.period.end)}</div>
            <h1>{num(c.kg_co2_per_piece, 2)} kg CO₂<br /><span>per casting</span></h1>
            <p className="lead">Electricity-related emissions for castings produced at {c.plant}, {c.location}, measured at the plant's main meter every minute.</p>
          </div>
          <div className="cert-table">
            <div><span>Reporting period</span><span>{dateRange(c.period.start, c.period.end)} ({num(c.period.days, 1)} days)</span></div>
            <div><span>Castings produced</span><span>{c.pieces.toLocaleString('en-IN')}</span></div>
            <div><span>Electricity consumed</span><span>{num(c.electricity_kwh, 1)} kWh</span></div>
            <div><span>Grid emission factor</span><span>{c.emission_factor_kg_per_kwh} kg CO₂/kWh <span className="placeholder">[CEA CO₂ Baseline Database, version]</span></span></div>
            <div><span>Total emissions</span><span>{num(c.total_co2_kg / 1000, 2)} t CO₂</span></div>
            <div><span>Scope</span><span>{c.scope}</span></div>
          </div>
          {daily.length > 1 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="mono" style={{ fontSize: 11, letterSpacing: 1.4, color: '#4E6154' }}>KG CO₂ PER CASTING, DAILY</div>
              <BarChart light data={daily.map((d) => ({ label: dayLabel(d.date), value: d.kg_co2_per_piece, highlight: worst && d.date === worst.date }))}
                ariaLabel={`Daily kg CO2 per casting: ${daily.map((d) => d.kg_co2_per_piece ?? 'no production').join(', ')}`} />
            </div>
          )}
          {avoidT > 0 && (
            <div className="cert-callout">
              <div className="v">−{num(avoidT, 1)} t</div>
              <p>CO₂ a year can be avoided with the {lowCost.length} low-cost fixes GreenGauge has identified at this plant, bringing each casting down to about <b>{num(perPieceAfter, 1)} kg</b>.</p>
            </div>
          )}
          <p className="method"><b>Method.</b> Electricity is metered at the main incomer at one-minute resolution. Castings are counted at the line. Emissions = electricity × grid emission factor, divided by castings produced in the same period. Covers purchased electricity only; fuels, materials and transport are not included.</p>
          <div className="cert-sign">
            <div><div className="line">[AUTHORISED SIGNATORY]</div><div className="who">{c.plant}</div></div>
            <div><div className="line">Issued [DATE]</div><div className="who">Generated by GreenGauge</div></div>
          </div>
        </div>
        <div className="cert-foot"><span>DEMONSTRATION STATEMENT · SIMULATED PLANT DATA</span><span>PAGE 1 OF 1</span></div>
      </article>
    </div>
  );
}
