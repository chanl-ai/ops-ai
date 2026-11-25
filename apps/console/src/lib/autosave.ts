import { keptEdits } from './kept-edits.ts';

/** What decides whether a waiting change may be sent now. */
export interface AutosaveState {
  /** The change waiting to be saved, as a string that differs whenever the change does; null when nothing waits. */
  waiting: string | null;
  enabled: boolean;
  /** The page is reading a newer copy; the next save would name the old one. */
  paused: boolean;
  saving: boolean;
  /** Someone else saved first: nothing is sent until the page has reloaded. */
  stale: string | null;
  /** What a save last failed on: sent again only once the change differs, or on Retry. */
  failed: string | null;
}

export const canSend = (s: AutosaveState): boolean => !!s.waiting && s.enabled && !s.paused && !s.saving && !s.stale && s.failed !== s.waiting;

/**
 * The edits to carry onto the saved version when it arrives: the fields changed after the save was sent, or null when
 * none were. The saved version redraws the form, so without this a change typed during the save is lost.
 */
export function carriedAfterSave<T extends object>(sent: T, now: T, arrived: T): T | null {
  const carried = keptEdits(sent, now, arrived);
  return JSON.stringify(carried) === JSON.stringify(arrived) ? null : carried;
}
