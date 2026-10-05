/**
 * The team the current user is working as. It is client state kept for the browser tab (like mock mode) and
 * travels with every API call: the HTTP client sends it as `X-Team-Id`, the mock reads it directly.
 */
export const DEFAULT_TEAM_ID = 'team_platform';
const KEY = 'ops-team';

const listeners = new Set<() => void>();
/** Holds the choice when sessionStorage is blocked, so it still lasts until reload. */
let memory: string | null = null;

export function currentTeamId(): string {
  if (typeof window === 'undefined') return DEFAULT_TEAM_ID;
  if (memory) return memory;
  try {
    return sessionStorage.getItem(KEY) ?? DEFAULT_TEAM_ID;
  } catch {
    return DEFAULT_TEAM_ID;
  }
}

export function setCurrentTeamId(id: string) {
  memory = id;
  try {
    sessionStorage.setItem(KEY, id);
  } catch {
    // Storage blocked: `memory` keeps the choice.
  }
  listeners.forEach((l) => l());
}

/** Subscribe/snapshot pair for useSyncExternalStore; the server render always uses the default team. */
export const teamStore = {
  subscribe(l: () => void) {
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  },
  get: currentTeamId,
  getServer: () => DEFAULT_TEAM_ID,
};
