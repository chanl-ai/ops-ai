/**
 * What's new and Coming next (c-510), ported from chanl-eval's What's New. Entries live one per file under the repo's
 * changelog/ and are read into the build (next.config.ts); the console never fetches them. The version, the update
 * banner and the remote fetch chanl-eval has are left out: the console deploys from this repo, so the date is the version.
 */

export interface ChangelogEntry {
  /** The entry's file name without .json: what the unread dot remembers. */
  id: string;
  date: string;
  title: string;
  description: string;
  tag: 'new' | 'improved' | 'fix';
}

export interface RoadmapItem {
  title: string;
  line: string;
}

const TAGS = new Set(['new', 'improved', 'fix']);

/** The entries newest first (by date, then title); anything malformed is left out rather than breaking the popover. */
export function parseChangelog(source: string): ChangelogEntry[] {
  let raw: unknown;
  try {
    raw = JSON.parse(source);
  } catch {
    return [];
  }
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((e): e is ChangelogEntry => !!e && typeof e.id === 'string' && typeof e.title === 'string' && typeof e.date === 'string' && TAGS.has(e.tag))
    .map(({ id, date, title, description, tag }) => ({ id, date, title, description: description ?? '', tag }))
    .sort((a, b) => b.date.localeCompare(a.date) || a.title.localeCompare(b.title));
}

export function parseRoadmap(source: string): RoadmapItem[] {
  try {
    const raw: unknown = JSON.parse(source);
    return Array.isArray(raw) ? raw.filter((i): i is RoadmapItem => !!i && typeof i.title === 'string').map(({ title, line }) => ({ title, line: line ?? '' })) : [];
  } catch {
    return [];
  }
}

/**
 * Whether an entry is unseen: any entry whose id the person has not seen, so a second entry the same day still shows
 * the dot. No entries, no dot.
 */
export function hasUnseen(entries: readonly ChangelogEntry[], seen: readonly string[]): boolean {
  const known = new Set(seen);
  return entries.some((e) => !known.has(e.id));
}
