import { useSyncExternalStore } from 'react';

/**
 * Sample rows for the /preview/settings mock, shared between a settings page and the dialog that opens the same form on
 * another page, so adding in one shows in the other. Mock data only; no service reads or writes it.
 */
export interface EgressHost {
  id: string;
  host: string;
  note: string;
  addedBy: string;
  addedAt: string;
}
export interface PreviewSecret {
  id: string;
  name: string;
  hint: string;
  teams: string[];
  lastUsedAt?: string;
  rotatedAt?: string;
}
export interface ModelAlias {
  id: string;
  alias: string;
  provider: string;
  model: string;
  clearance: string;
}

const ago = (mins: number) => new Date(Date.now() - mins * 60_000).toISOString();

interface State {
  hosts: EgressHost[];
  secrets: PreviewSecret[];
  aliases: ModelAlias[];
}

let state: State = {
  hosts: [
    { id: 'eh_2m9k4w81', host: 'api.corebank.harborpine.example', note: 'Core banking read API', addedBy: 'Sam Adeyemi', addedAt: ago(60 * 24 * 12) },
    { id: 'eh_7c1p5x3d', host: 'statements.harborpine.example', note: 'Statement renderer', addedBy: 'Sam Adeyemi', addedAt: ago(60 * 24 * 5) },
  ],
  secrets: [
    { id: 'sc_4a8f2e61', name: 'STATEMENTS_KEY', hint: '4f2a', teams: ['Operations'], lastUsedAt: ago(14), rotatedAt: ago(60 * 24 * 20) },
    { id: 'sc_9d3b7c05', name: 'CORE_BANK_TOKEN', hint: 'c91e', teams: [], lastUsedAt: ago(3), rotatedAt: ago(60 * 24 * 41) },
  ],
  aliases: [
    { id: 'ma_1f6e8a22', alias: 'advisor-default', provider: 'Harbor & Pine OpenAI', model: 'gpt-5.1', clearance: 'Internal' },
    { id: 'ma_5b0c3d97', alias: 'policy-strict', provider: 'Harbor & Pine Anthropic', model: 'claude-sonnet-4-5', clearance: 'Confidential' },
  ],
};
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const subscribe = (l: () => void) => (listeners.add(l), () => void listeners.delete(l));
const rid = (p: string) => `${p}_${Math.random().toString(36).slice(2, 10)}`;

export const previewStore = {
  addHost: (host: string, note: string) => {
    state = { ...state, hosts: [{ id: rid('eh'), host, note, addedBy: 'Sam Adeyemi', addedAt: new Date().toISOString() }, ...state.hosts] };
    emit();
  },
  removeHost: (id: string) => ((state = { ...state, hosts: state.hosts.filter((h) => h.id !== id) }), emit()),
  addSecret: (name: string, value: string, teams: string[]) => {
    state = { ...state, secrets: [{ id: rid('sc'), name, hint: value.slice(-4).padStart(4, '•'), teams, rotatedAt: new Date().toISOString() }, ...state.secrets] };
    emit();
  },
  addAlias: (alias: string, provider: string, model: string, clearance: string) => {
    state = { ...state, aliases: [{ id: rid('ma'), alias, provider, model, clearance }, ...state.aliases] };
    emit();
  },
};

export function usePreviewStore<T>(pick: (s: State) => T): T {
  return useSyncExternalStore(subscribe, () => pick(state), () => pick(state));
}

export const VIEWER_ROLES = ['Builder', 'Admin', 'Security admin'] as const;
export type ViewerRole = (typeof VIEWER_ROLES)[number];

let viewer: ViewerRole = 'Security admin';
const viewerListeners = new Set<() => void>();
export const setViewerRole = (r: ViewerRole) => ((viewer = r), viewerListeners.forEach((l) => l()));

/** The role the mock is drawn for, so each page can show its locked state; Security admin may do everything, Admin everything but Security's. */
export function useViewerRole() {
  const role = useSyncExternalStore(
    (l) => (viewerListeners.add(l), () => void viewerListeners.delete(l)),
    () => viewer,
    () => viewer,
  );
  const can = (needed: string) => (role === 'Security admin' ? true : role === 'Admin' ? needed !== 'Security admin' : needed === 'Builder');
  return { role, can };
}
