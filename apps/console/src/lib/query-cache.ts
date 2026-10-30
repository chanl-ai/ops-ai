/**
 * The console's saved query cache (c-560): what a person's screens read is kept in IndexedDB, so a reload shows it at
 * once and refreshes it behind. One copy per person and team, dropped when the app version changes or after 24 hours.
 *
 * A write changes what the screens read, so the saved copy never outlives one: when a write starts the copy is removed
 * and nothing is saved until it settles; then the copy is saved at once, without the reads the write marked out of date
 * (`isInvalidated`), which come back fresh on the next screen that needs them. A reload just after a change therefore
 * never shows the answer from before it.
 *
 * Only data a screen reads for the current team is saved (its key ends with that `{ team }`). Never saved: the
 * session's own reads (who the person is, their permissions and teams, the sign-in policy), since a stale permission
 * would enable Approve or Run; Human Tasks, which a person decides and must see as they are now; a run that has not
 * finished; and a file preview's signed link, which expires.
 *
 * Kept free of `@/` imports so `node --test` can load it.
 */
import type { Query, QueryClient, QueryKey } from '@tanstack/react-query';
import { persistQueryClientRestore, persistQueryClientSave, type PersistedClient, type Persister } from '@tanstack/react-query-persist-client';
import { clear, createStore, del, get, set, type UseStore } from 'idb-keyval';

import { versionLabel } from './version.ts';

export const MAX_AGE_MS = 24 * 60 * 60_000;
/** Saves are batched: dehydrating the cache on every cache event would cost more than the reads it saves. */
const SAVE_AFTER_MS = 1_000;

const SESSION_ROOTS = new Set(['me', 'teams', 'sign-in-policy', 'sign-in-options', 'demo-people']);
const NEVER_ROOTS = new Set(['reviews']);
/** Keys of one run: saved only once the run has finished. */
const SINGLE_RUN: QueryKey[] = [['cases', 'run'], ['cases', 'run-state'], ['engine', 'run'], ['eval-run'], ['knowledge', 'run']];
const FINISHED = new Set(['succeeded', 'failed', 'cancelled', 'completed']);

/** Whether this build saves the cache: on unless the install sets NEXT_PUBLIC_OPS_CACHE=off. */
export function cacheOn(setting: string | undefined): boolean {
  return setting?.trim().toLowerCase() !== 'off';
}

/** The version a saved cache must match; a build with no version still busts on its own fixed value. */
export function cacheBuster(tag: string | undefined, commit: string | undefined): string {
  return versionLabel(tag, commit) ?? 'unversioned';
}

const startsWith = (key: QueryKey, prefix: QueryKey) => prefix.every((part, i) => key[i] === part);

/** Whether a query may be saved for `team`. */
export function shouldSave(query: { queryKey: QueryKey; state: { status: string; data?: unknown; isInvalidated?: boolean } }, team: string): boolean {
  const key = query.queryKey;
  if (query.state.status !== 'success' || query.state.isInvalidated) return false;
  const last = key[key.length - 1] as { team?: unknown } | undefined;
  if (!last || typeof last !== 'object' || Object.keys(last).length !== 1 || last.team !== team) return false;
  const root = String(key[0]);
  if (SESSION_ROOTS.has(root) || NEVER_ROOTS.has(root)) return false;
  if (startsWith(key, ['files', 'preview-link'])) return false;
  if (SINGLE_RUN.some((prefix) => startsWith(key, prefix))) {
    return FINISHED.has(String((query.state.data as { status?: unknown } | undefined)?.status));
  }
  return true;
}

let store: UseStore | null = null;
const queriesStore = () => (store ??= createStore('ops-console', 'queries'));
/** Bumped by every wipe: a save started before it writes nothing. */
let generation = 0;

/** Removes every saved copy, for every person and team in this browser. */
export async function wipeSavedQueries(): Promise<void> {
  generation += 1;
  if (typeof indexedDB === 'undefined') return;
  try {
    await clear(queriesStore());
  } catch {
    // Storage blocked (private window): nothing was saved.
  }
}

/**
 * Puts the saved copy into the cache, then marks all of it out of date. A restored query keeps the time it was fetched,
 * so a copy saved within the stale time would otherwise count as fresh and show the old answer with no refetch; marked
 * out of date, every screen shows it at once and fetches the current answer behind it.
 */
export async function restoreSaved(client: QueryClient, persister: Persister, buster: string): Promise<void> {
  await persistQueryClientRestore({ queryClient: client, persister, maxAge: MAX_AGE_MS, buster }).catch(() => undefined);
  void client.invalidateQueries();
}

export interface SavedQueries {
  /** Shows the saved copy, when one matches this version and is under a day old. */
  restore(): Promise<void>;
  /** Saves the team's reads as they change; returns the stop. */
  start(): () => void;
}

/** The saved cache for one person in one team, or null when the install turned it off or nobody is signed in. */
export function openSavedQueries(options: { client: QueryClient; user: string | null; team: string | null; buster: string; setting: string | undefined }): SavedQueries | null {
  const { client, user, team, buster } = options;
  if (!cacheOn(options.setting) || !user || !team) return null;
  const key = `${user}:${team}`;
  const persister: Persister = {
    persistClient: (saved: PersistedClient) => set(key, saved, queriesStore()),
    restoreClient: () => get<PersistedClient>(key, queriesStore()),
    removeClient: () => del(key, queriesStore()),
  };
  const dehydrateOptions = { shouldDehydrateQuery: (q: Query) => shouldSave(q, team), shouldDehydrateMutation: () => false };
  return {
    restore: () => restoreSaved(client, persister, buster),
    start() {
      const at = generation;
      let timer: ReturnType<typeof setTimeout> | undefined;
      // A wipe bumps the generation before it clears, and IndexedDB runs write transactions in the order they were
      // opened, so a save checked here lands either before the clear or not at all.
      const current: Persister = { ...persister, persistClient: async (saved) => (at === generation ? persister.persistClient(saved) : undefined) };
      const save = () => {
        clearTimeout(timer);
        timer = undefined;
        if (at !== generation || client.isMutating() > 0) return;
        void persistQueryClientSave({ queryClient: client, persister: current, buster, dehydrateOptions }).catch(() => undefined);
      };
      const off = client.getQueryCache().subscribe((e) => {
        if ((e.type === 'added' || e.type === 'removed' || e.type === 'updated') && !timer) timer = setTimeout(save, SAVE_AFTER_MS);
      });
      const offWrites = client.getMutationCache().subscribe((e) => {
        if (e.type !== 'updated') return;
        const status = e.mutation.state.status;
        if (status === 'pending') {
          // Whatever is saved may be what this write changes: gone now, before its answer, so a reload mid-write reads
          // fresh. The pause in `save` keeps a batched save from writing the old answers back meanwhile.
          clearTimeout(timer);
          timer = undefined;
          if (at === generation) void Promise.resolve(persister.removeClient()).catch(() => undefined);
        } else if ((status === 'success' || status === 'error') && client.isMutating() === 0) {
          // The write's own invalidations have run by now (a mutation settles after its onSuccess), so this saves at
          // once without the reads it made out of date.
          save();
        }
      });
      return () => {
        off();
        offWrites();
        clearTimeout(timer);
      };
    },
  };
}
