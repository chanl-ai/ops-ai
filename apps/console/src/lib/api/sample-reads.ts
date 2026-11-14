/**
 * Which pages read sample data while real services answer beside them. The served-route table in index.ts says which
 * page prefixes a service serves, but a page under a served prefix can still call an area that is the mock's (the MCP
 * page sat under /build/channels and read mock data). So every mock call made beside real services is recorded here,
 * by the page it was made on, and the page says so (PageLayout) and the use-case harness fails on it.
 */

/** The console line a mock read writes; packages/usecase-runner/src/harness.ts reads it. Keep both in step. */
export const SAMPLE_READ_MARK = '[ops-ai sample data]';

/**
 * Reads the app shell makes on every page (the sign-in policy the guard reads in app-shell.tsx, the sidebar's lookups),
 * kept under `*` rather than the page that happened to load first, so they do not mark every page as sample data.
 * They are still sample data on a platform stack; test-results/sample-data-pages.md lists them as their own row.
 */
const SHELL = new Set(['signInPolicy.get', 'lookups.get']);
export const SHELL_PATH = '*';

const byPath = new Map<string, Set<string>>();
const listeners = new Set<() => void>();

function record(area: string): void {
  if (typeof window === 'undefined') return;
  const path = SHELL.has(area) ? SHELL_PATH : window.location.pathname;
  const seen = byPath.get(path) ?? new Set<string>();
  if (seen.has(area)) return;
  seen.add(area);
  byPath.set(path, seen);
  console.warn(`${SAMPLE_READ_MARK} ${area} on ${path}`);
  for (const l of listeners) l();
}

/** The mock areas a page has read since the console loaded, so a page drawn from the query cache still says so. */
export function sampleReadsOn(path: string): string[] {
  return [...(byPath.get(path) ?? [])];
}

export function subscribeSampleReads(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * `api` with every call it still makes to `mock` recorded: a function is the mock's when it is the same function the
 * mock holds at the same place, which survives the `{ ...mock.area, one: real }` overrides index.ts makes. Only calls
 * that return a promise count, so sync helpers (a snippet's URL) are not reads.
 */
export function recordMockReads<T extends object>(api: T, mock: T, path = ''): T {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(api)) {
    const theirs = (mock as Record<string, unknown>)[key];
    const where = path ? `${path}.${key}` : key;
    if (typeof value === 'function' && value === theirs) {
      out[key] = function recorded(this: unknown, ...args: unknown[]) {
        const result = (value as (...a: unknown[]) => unknown).apply(this, args);
        if (result && typeof (result as Promise<unknown>).then === 'function') record(where);
        return result;
      };
    } else if (value && typeof value === 'object' && !Array.isArray(value) && theirs && typeof theirs === 'object') {
      // Only plain objects are copied: a class instance would lose its prototype's methods.
      out[key] = Object.getPrototypeOf(value) === Object.prototype ? recordMockReads(value as object, theirs as object, where) : value;
    } else {
      out[key] = value;
    }
  }
  return out as T;
}
