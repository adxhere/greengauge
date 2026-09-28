import { useEffect, useRef, useState } from 'react';

// Demo snapshot mode (the Vercel build): read recorded API responses from /demo/*.json
export const DEMO = import.meta.env.VITE_DEMO === 'true';
export function demoPath(path) {
  return '/demo/' + path.replace(/^\/api\//, '').replace(/[?&=/]/g, '_') + '.json';
}

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function getJSON(path) {
  const res = await fetch(DEMO ? demoPath(path) : path, { headers: { accept: 'application/json' } });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not JSON */ }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

// Fetch a path now and then every `intervalMs`, keeping the last good data on screen.
export function usePoll(path, intervalMs = 15000) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    let timer;
    const tick = async () => {
      try {
        const data = await getJSON(path);
        if (alive.current) setState({ data, error: null, loading: false });
      } catch (error) {
        if (alive.current) setState((s) => ({ data: s.data, error, loading: false }));
      }
      if (alive.current && !DEMO) timer = setTimeout(tick, intervalMs);
    };
    setState((s) => ({ ...s, loading: true }));
    tick();
    return () => { alive.current = false; clearTimeout(timer); };
  }, [path, intervalMs]);

  return state;
}
