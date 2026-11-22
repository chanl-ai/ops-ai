/**
 * The copy a save was made on. An agent and a skill are each edited as one draft that is rewritten in place under one
 * version number, so a save names the version and the digest it read; the service refuses one made from an older copy
 * (409 `stale_base`) and says who saved the newest copy and when.
 */
export interface SaveBase {
  baseVersion: number;
  baseDigest: string;
}

/** The base a save names, from the agent or skill as last read. A list row has no digest and names no copy. */
export const baseOf = (read: { version: number; digest?: string | null }): SaveBase => ({ baseVersion: read.version, baseDigest: read.digest ?? '' });

export interface StaleSave {
  /** The newest version's number. */
  version: number | null;
  savedBy: string;
  savedAt: string;
}

/** Who saved the newer copy, when `e` is a save refused as stale; null for any other error. */
export function staleSave(e: unknown): StaleSave | null {
  const err = e as { code?: string; details?: Record<string, unknown> } | null;
  if (err?.code !== 'stale_base') return null;
  const version = Number(err.details?.version);
  return { version: Number.isFinite(version) ? version : null, savedBy: String(err.details?.savedBy ?? ''), savedAt: String(err.details?.savedAt ?? '') };
}

/** Who saved the newer copy and when, as a page says it. */
export function staleNote(stale: StaleSave): string {
  const at = stale.savedAt ? new Date(stale.savedAt) : null;
  const time = at && !Number.isNaN(at.getTime()) ? ` at ${at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : '';
  return `${stale.savedBy || 'Someone else'} saved a newer draft${time}.`;
}

/**
 * What an autosaving page does with a refused save. The person's own write to the draft the page read (their @ insert,
 * a grant, a second tab) needs no message: the page reads the newest copy and sends the change again. Anything else is
 * said, and nothing more is sent until the person chooses: another person's save, or a newest copy under a different
 * version number than the one read, which more than this person's last write stands behind.
 */
export function onStaleSave(stale: StaleSave, me: string | undefined, readVersion: number): { resend: true } | { resend: false; note: string } {
  return me && stale.savedBy === me && stale.version === readVersion ? { resend: true } : { resend: false, note: staleNote(stale) };
}
