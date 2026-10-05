export const money = (n: number, currency = 'CAD') =>
  n.toLocaleString('en-CA', { style: 'currency', currency, maximumFractionDigits: n < 100 ? 2 : 0 });

export const pct = (n: number) => `${Math.round(n * 100)}%`;

export const count = (n: number) => n.toLocaleString('en-CA');

export function relativeTime(iso?: string) {
  if (!iso) return '—';
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h}h ago`;
  return new Date(iso).toLocaleDateString('en-CA', { month: 'short', day: 'numeric' });
}

export const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

/** A record id shortened for display: the prefix dropped, last six characters, e.g. `evr_9f3a21c7` → `#3a21c7`. */
export const shortId = (id: string) => `#${id.replace(/^[a-z]+[_-]/i, '').slice(-6)}`;

/** `3 agents`, `1 agent`. */
export const plural = (n: number, word: string, many = `${word}s`) => `${n.toLocaleString('en-CA')} ${n === 1 ? word : many}`;

export function dateTime(iso?: string) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-CA', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}

export function shortDate(iso?: string) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-CA', { day: 'numeric', month: 'short', year: 'numeric' });
}

/** A calendar date ("2026-10-01") as "1 Oct 2026". Read at local noon so the day does not shift by time zone. */
export function dateOnly(ymd?: string | null) {
  if (!ymd) return '—';
  return /^\d{4}-\d{2}-\d{2}$/.test(ymd) ? shortDate(`${ymd}T12:00:00`) : shortDate(ymd);
}

/** A free-text extracted value, with calendar dates formatted. */
export const fieldValue = (v: string | null) => (v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? dateOnly(v) : v);

export function bytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

/** Milliseconds as `412 ms` or `1.9 s`. */
export const ms = (n: number) => (n < 1000 ? `${Math.round(n)} ms` : `${(n / 1000).toFixed(1)} s`);

/** Seconds as `45 s`, `6 min 52 s` or `1 h 4 min`. */
export function duration(sec: number) {
  if (sec < 60) return `${sec} s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m < 60) return s ? `${m} min ${s} s` : `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function mimeLabel(mime: string) {
  if (mime === 'application/pdf') return 'PDF';
  if (mime.includes('wordprocessingml')) return 'DOCX';
  if (mime.includes('spreadsheetml')) return 'XLSX';
  if (mime.includes('presentationml')) return 'PPTX';
  if (mime === 'text/csv') return 'CSV';
  if (mime === 'text/markdown') return 'MD';
  if (mime === 'text/html') return 'HTML';
  if (mime === 'text/plain') return 'TXT';
  return mime.split('/').pop()?.toUpperCase() ?? mime;
}
