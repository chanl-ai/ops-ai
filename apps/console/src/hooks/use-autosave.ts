'use client';

import * as React from 'react';

import { type AutosaveState, canSend } from '@/lib/autosave';
import type { SaveStatus } from '@/lib/save-state-gate';

/** What to do with a refused save: send the change again on the newest copy, stop with a note, or neither. */
export type Refusal = { resend: true } | { stale: string } | null;

export interface AutosaveOptions<R> {
  /** The change waiting to be saved, as a string that differs whenever the change does; null when nothing waits. */
  waiting: string | null;
  /** The person may edit and every field is valid. */
  enabled: boolean;
  /** The page is reading a newer copy, so a save now would name the old one. */
  paused?: boolean;
  /** Sends the change. Rejects when the save fails. */
  send: () => Promise<R>;
  /** Runs once a save went through, with what `waiting` was when it was sent. */
  onSaved?: (result: R, sent: string) => void;
  /** Classifies a failed save; anything not named here is a plain failure. */
  refusal?: (e: unknown) => Refusal;
  /** Runs for a failure that is neither a resend nor stale, so a page can say which field it was. */
  onError?: (e: unknown) => void;
  /** Reads the newest copy after the person's own write made the save stale; needed for `{ resend: true }`. */
  readNewest?: () => Promise<unknown>;
  /** Anything else that should re-arm the save once it moves, such as the saved copy the patch is read from. */
  settledOn?: unknown;
  delayMs?: number;
}

/**
 * The one autosave: a second after the last change, with no dialog and no note per save. A save that fails is not sent
 * again until the change differs or `retry` is pressed. One refused because the page holds an old copy is handled by
 * the page's `refusal`: `{ resend: true }` reads the newest copy once and sends again (the person's own write); `{ stale }`
 * says who saved first and sends nothing until `clearStale`, once the page has reloaded onto their copy.
 */
export function useAutosave<R>(o: AutosaveOptions<R>) {
  const [saving, setSaving] = React.useState(false);
  const [failed, setFailed] = React.useState<{ key: string; message: string } | null>(null);
  const [stale, setStale] = React.useState<string | null>(null);
  const [rereading, setRereading] = React.useState(false);
  // What was last sent again after the person's own write, so one change is sent again once.
  const resent = React.useRef<string | null>(null);
  const latest = React.useRef(o);
  latest.current = o;

  const saveNow = React.useCallback(async () => {
    const { waiting: sent, send, onSaved, refusal, readNewest } = latest.current;
    if (!sent) return;
    setSaving(true);
    try {
      const result = await send();
      setFailed(null);
      resent.current = null;
      onSaved?.(result, sent);
    } catch (e) {
      const next = refusal?.(e) ?? null;
      if (next && 'resend' in next && readNewest && resent.current !== sent) {
        resent.current = sent;
        setRereading(true);
        await readNewest().catch(() => undefined);
        setRereading(false);
      } else if (next && 'stale' in next) {
        setStale(next.stale);
      } else {
        latest.current.onError?.(e);
        setFailed({ key: sent, message: e instanceof Error ? e.message : 'The change was not saved' });
      }
    } finally {
      setSaving(false);
    }
  }, []);

  const gate: AutosaveState = { waiting: o.waiting, enabled: o.enabled, paused: !!o.paused || rereading, saving, stale, failed: failed?.key ?? null };
  const open = canSend(gate);
  React.useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => void saveNow(), o.delayMs ?? 1000);
    return () => clearTimeout(t);
    // Re-armed by a change, and once the last save, a read or a stale notice has settled.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, o.waiting, o.settledOn, saveNow]);

  const failedNow = failed && failed.key === o.waiting ? failed : null;
  const status: SaveStatus = stale ? 'stale' : saving ? 'saving' : failedNow ? 'failed' : o.waiting ? 'unsaved' : 'saved';
  return {
    saveNow,
    status,
    saving,
    /** What the last failed save said, while that change is still the one waiting. */
    error: failedNow?.message ?? null,
    stale,
    /** The page has moved onto the newest copy: saving may start again. */
    clearStale: () => (setStale(null), setFailed(null)),
    retry: () => (setFailed(null), void saveNow()),
    reading: rereading,
  };
}
