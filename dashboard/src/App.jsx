import { useEffect, useState } from 'react';
import { usePoll } from './api.js';
import Sidebar from './components/Sidebar.jsx';
import Overview from './pages/Overview.jsx';
import Live from './pages/Live.jsx';
import Fixes from './pages/Fixes.jsx';
import Health from './pages/Health.jsx';
import Certificate from './pages/Certificate.jsx';

const PAGES = { overview: Overview, live: Live, fixes: Fixes, health: Health, certificate: Certificate };
const TITLES = { overview: 'Overview', live: 'Live plant', fixes: 'Fixes & payback', health: 'Plant health', certificate: 'Carbon certificate' };

function currentPage() {
  const id = window.location.hash.replace(/^#\/?/, '');
  return PAGES[id] ? id : 'overview';
}

export default function App() {
  const [page, setPage] = useState(currentPage);
  const [days, setDays] = useState(7);
  const health = usePoll('/api/health', 10000);
  const config = usePoll('/api/config', 300000);

  useEffect(() => {
    const onHash = () => { setPage(currentPage()); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  useEffect(() => { document.title = `${TITLES[page]} · GreenGauge`; }, [page]);

  const Page = PAGES[page];
  const apiDown = health.error && !health.data;
  const waiting = health.data?.status === 'waiting_for_data';

  return (
    <div className="app">
      <Sidebar page={page} plant={config.data?.site} />
      <main className="main">
        {apiDown ? (
          <Waiting title="Can't reach the analytics service" text="The dashboard is up, but the analytics API isn't answering. Start the whole stack from the project folder:" cmd="docker compose up --build" />
        ) : waiting ? (
          <Waiting title="Waiting for plant data" text="The analytics service is running, but there are no readings yet. Give the pipeline a minute, or load three days of history now:" cmd="docker compose exec analytics python tools/backfill.py --scenario faulty" />
        ) : (
          <Page days={days} setDays={setDays} />
        )}
      </main>
    </div>
  );
}

function Waiting({ title, text, cmd }) {
  return (
    <div className="waiting" role="status">
      <h1>{title}</h1>
      <p>{text}</p>
      <code>{cmd}</code>
      <p className="muted" style={{ fontSize: 13 }}>This page checks again every 10 seconds.</p>
    </div>
  );
}
