// Number and time formatting, Indian style.

export function inr(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const neg = n < 0;
  const s = String(Math.round(Math.abs(n)));
  let out = s;
  if (s.length > 3) {
    let head = s.slice(0, -3);
    const parts = [];
    while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
    if (head) parts.unshift(head);
    out = parts.join(',') + ',' + s.slice(-3);
  }
  return (neg ? '−₹' : '₹') + out;
}

// ₹7.97 L for lakhs, ₹1.2 Cr for crores, plain rupees below a lakh
export function money(n) {
  if (n === null || n === undefined) return '—';
  if (Math.abs(n) >= 1e7) return '₹' + (n / 1e7).toFixed(2) + ' Cr';
  if (Math.abs(n) >= 1e5) return '₹' + (n / 1e5).toFixed(2) + ' L';
  return inr(n);
}

export function num(n, digits = 1) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return Number(n).toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

const TZ = 'Asia/Kolkata';

export function clock(iso) {
  return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: TZ });
}

export function dayLabel(isoDate) {
  // "2026-09-09" -> "WED 9"
  const d = new Date(isoDate + 'T12:00:00+05:30');
  const wd = d.toLocaleDateString('en-GB', { weekday: 'short', timeZone: TZ }).toUpperCase();
  return `${wd} ${d.toLocaleDateString('en-GB', { day: 'numeric', timeZone: TZ })}`;
}

export function longDate(iso) {
  return new Date(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: TZ });
}

export function dateRange(startIso, endIso) {
  const s = new Date(startIso), e = new Date(endIso);
  const sameMonth = s.toLocaleDateString('en-GB', { month: 'short', timeZone: TZ }) === e.toLocaleDateString('en-GB', { month: 'short', timeZone: TZ });
  const sd = s.toLocaleDateString('en-GB', { day: 'numeric', timeZone: TZ });
  const ed = e.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: TZ });
  return sameMonth ? `${sd}–${ed}` : `${s.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: TZ })} – ${ed}`;
}

export function duration(minutes) {
  const m = Math.round(minutes);
  const h = Math.floor(m / 60);
  return h ? `${h} h ${m % 60} min` : `${m} min`;
}

const NAMES = {
  lighting_aux: 'Lighting & aux',
  main_incomer: 'Main incomer',
};

export function machineName(device) {
  if (NAMES[device]) return NAMES[device];
  const s = device.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export const CATEGORY = {
  compressed_air: 'Compressed air',
  idle_running: 'Idle running',
  power_quality: 'Power quality',
  maintenance: 'Maintenance',
};
