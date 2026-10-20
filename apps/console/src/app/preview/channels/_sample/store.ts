import { useSyncExternalStore } from 'react';

import { previewStore } from '@/lib/settings-preview-store';

import { CONNECTIONS, FOLDERS, MAIL_SECRETS, REVOKED_SECRET, TRIGGER_WORKFLOW, type Connection, type MailboxSettings, type Serves } from './data';

/**
 * The channels mock's state, shared by the channels pages, the mailbox drawer and the trigger mock, so a mailbox
 * connected in one shows in the others. Secrets live in the settings mock's store: picking or adding one here is the
 * same list as Govern › Security.
 */
let connections: Connection[] = CONNECTIONS;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const subscribe = (l: () => void) => (listeners.add(l), () => void listeners.delete(l));

// The secrets the sample mailboxes name join the Secrets list once, when this module loads rather than during a render.
// The flag sits on globalThis because a hot reload evaluates this module again while the settings store keeps its rows.
const seededFlag = globalThis as { __channelsPreviewSecrets?: boolean };
if (!seededFlag.__channelsPreviewSecrets) {
  seededFlag.__channelsPreviewSecrets = true;
  for (const name of MAIL_SECRETS) previewStore.addSecret(name, `sample-${name.length}a${name.length}c`, ['Operations']);
}

export function useConnections(): Connection[] {
  return useSyncExternalStore(subscribe, () => connections, () => connections);
}

export function useConnection(id: string): Connection | undefined {
  return useConnections().find((c) => c.id === id);
}

export type TestStep = { title: string; state: 'pending' | 'running' | 'done' | 'failed' };
export interface TestResult {
  ok: boolean;
  steps: TestStep[];
  message: string;
  folders?: string[];
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

export const channelsStore = {
  /** Adds a connected mailbox and returns its id. */
  connectMailbox: (name: string, settings: MailboxSettings, team = 'Operations'): string => {
    const id = `mbx_${Math.random().toString(16).slice(2, 10)}`;
    // Serves nothing until a workflow's Email received trigger picks it.
    connections = [{ id, type: 'email', name, serves: { kind: 'workflow', id: '', version: 'latest' }, traffic24h: 0, errors24h: 0, activity7d: 0, detail: settings.address, status: 'connected', lastActivityAt: new Date().toISOString(), team, workflows: [], mailbox: settings }, ...connections];
    emit();
    return id;
  },
  updateMailbox: (id: string, settings: MailboxSettings) => {
    connections = connections.map((c) => (c.id === id ? { ...c, detail: settings.address, mailbox: settings, ...(c.status === 'attention' && settings.secret !== REVOKED_SECRET ? { status: 'connected' as const, problem: undefined } : {}) } : c));
    emit();
  },
  /** Points a connection at another workflow or agent, or another version of the same one. */
  setServes: (id: string, serves: Serves) => {
    connections = connections.map((c) => (c.id === id ? { ...c, serves } : c));
    emit();
  },
  setPaused: (id: string, paused: boolean) => {
    connections = connections.map((c) => (c.id === id ? { ...c, status: paused ? 'paused' : 'connected' } : c));
    emit();
  },
  /** Binds the trigger mock's workflow to one mailbox, and unbinds it from any other: a trigger reads one mailbox. */
  bindTrigger: (mailboxId: string | null) => {
    connections = connections.map((c) => {
      const others = c.workflows.filter((w) => w.id !== TRIGGER_WORKFLOW.id);
      return c.id === mailboxId ? { ...c, workflows: [...others, TRIGGER_WORKFLOW] } : others.length === c.workflows.length ? c : { ...c, workflows: others };
    });
    emit();
  },
  /**
   * What a test does on the server: sign in with the secret, open the folder, read the newest message. Walks the steps
   * with a pause so the result reads as it arrives. A missing secret or the revoked one fails at sign-in.
   */
  test: async (settings: MailboxSettings, onStep: (steps: TestStep[]) => void): Promise<TestResult> => {
    const titles = ['Sign in', `Open ${settings.folder}`, 'Read the newest message'];
    const steps: TestStep[] = titles.map((title) => ({ title, state: 'pending' }));
    const show = () => onStep(steps.map((s) => ({ ...s })));
    for (let i = 0; i < steps.length; i++) {
      steps[i].state = 'running';
      show();
      await wait(350);
      if (i === 0 && (!settings.secret || settings.secret === REVOKED_SECRET)) {
        steps[i].state = 'failed';
        show();
        return { ok: false, steps, message: settings.secret ? `${settings.address || 'The server'} refused the password in ${settings.secret}. Make a new app password and rotate the secret.` : 'Pick the secret that holds the password first.' };
      }
      steps[i].state = 'done';
      show();
    }
    return { ok: true, steps, message: `Newest in ${settings.folder}: “Garnishment order 2026-1184”, 12 minutes ago. Nothing was marked read.`, folders: FOLDERS };
  },
};
