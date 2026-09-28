import { DEMO } from '../api.js';

export function GaugeMark({ size = 34 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 34 34" aria-hidden="true">
      <path d="M6.4 27.6 A15 15 0 1 1 27.6 27.6" fill="none" stroke="#3DCD58" strokeWidth="3" strokeLinecap="round" />
      <line x1="17" y1="17" x2="24.5" y2="10.5" stroke="#EAF2EC" strokeWidth="2.6" strokeLinecap="round" />
      <circle cx="17" cy="17" r="2.8" fill="#EAF2EC" />
    </svg>
  );
}

const icon = { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true };

const LINKS = [
  { id: 'overview', label: 'Overview', svg: <svg {...icon}><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></svg> },
  { id: 'live', label: 'Live plant', svg: <svg {...icon}><circle cx="12" cy="12" r="2" /><path d="M16.2 7.8a6 6 0 0 1 0 8.4M7.8 16.2a6 6 0 0 1 0-8.4M19 5a10 10 0 0 1 0 14M5 19A10 10 0 0 1 5 5" /></svg> },
  { id: 'fixes', label: 'Fixes & payback', svg: <svg {...icon}><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z" /></svg> },
  { id: 'health', label: 'Plant health', svg: <svg {...icon}><path d="M3 12h4l3-8 4 16 3-8h4" /></svg> },
  { id: 'certificate', label: 'Carbon certificate', svg: <svg {...icon}><path d="M11 20A7 7 0 0 1 4 13c0-6 6-9 16-9 0 10-3 16-9 16z" /><path d="M4 20c4-4 7-6 11-8" /></svg> },
];

export default function Sidebar({ page, plant }) {
  return (
    <nav className="side" aria-label="Main navigation">
      <a className="brand" href="#/overview" aria-label="GreenGauge home">
        <GaugeMark />
        <span className="brand-name">Green<span>Gauge</span></span>
      </a>
      {plant && (
        <div className="plant-card">
          <div className="name">{plant.name}</div>
          <div className="meta">{[plant.location?.split(',')[0], plant.product].filter(Boolean).join(' · ')}</div>
        </div>
      )}
      <div className="nav">
        {LINKS.map((l) => (
          <a key={l.id} href={`#/${l.id}`} aria-current={page === l.id ? 'page' : undefined}>{l.svg}{l.label}</a>
        ))}
      </div>
      <div className="side-foot">
        <div className="event">YUVA YODHA ENERGY TECH HACKATHON<br />TRACK 4 · SMART MANUFACTURING</div>
        <div className="tag-dashed">{DEMO ? 'DEMO SNAPSHOT' : 'SIMULATED PLANT DATA'}</div>
      </div>
    </nav>
  );
}
