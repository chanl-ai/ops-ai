export type SaveStatus = 'saved' | 'unsaved' | 'saving' | 'failed' | 'stale';

/** A save quicker than this never shows "Saving…": the line goes from Unsaved to Saved. */
export const SHOW_SAVING_AFTER_MS = 300;
/** Once "Saving…" shows it stays this long, so it is readable and does not flicker on a fast second save. */
export const KEEP_SAVING_MS = 600;

export interface Gate {
  shown: SaveStatus;
  /** When the current run of `saving` began, before it was shown. */
  since: number | null;
  /** When `saving` was put on screen. */
  shownAt: number | null;
}

export const newGate = (shown: SaveStatus): Gate => ({ shown, since: null, shownAt: null });

/**
 * What the header shows for the state the page is in at `now`, and when to ask again (`wakeAt`). A pure function of
 * time so the no-flash rule is checked without a clock; the hook in components/shared/save-state.tsx supplies the timers.
 */
export function settle(g: Gate, want: SaveStatus, now: number): { shown: SaveStatus; wakeAt: number | null } {
  let wakeAt: number | null = null;
  if (want === 'saving') {
    g.since ??= now;
    if (g.shown === 'saving') {
      // already on screen
    } else if (now - g.since >= SHOW_SAVING_AFTER_MS) {
      g.shown = 'saving';
      g.shownAt = now;
    } else wakeAt = g.since + SHOW_SAVING_AFTER_MS;
  } else {
    g.since = null;
    if (want === 'failed' || want === 'stale') g.shown = want;
    else if (g.shown === 'saving' && g.shownAt !== null && now - g.shownAt < KEEP_SAVING_MS) wakeAt = g.shownAt + KEEP_SAVING_MS;
    else g.shown = want;
  }
  return { shown: g.shown, wakeAt };
}

type KeyEvent = Pick<KeyboardEvent, 'key' | 'metaKey' | 'ctrlKey' | 'shiftKey' | 'altKey'>;

/** `mod+s` is Cmd+S on a Mac and Ctrl+S elsewhere; a combo is `mod+` then a key, with no other modifier. */
export function shortcutMatches(combo: string, e: KeyEvent): boolean {
  const key = combo.replace(/^mod\+/, '');
  return (e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === key;
}
