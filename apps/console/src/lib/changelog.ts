/**
 * What's new and Coming next. Unreleased changes are fragments, one per file under the repo's changelog/; each release
 * is one file under changelog/releases/ (scripts/changelog-fold.mjs). next.config.ts reads both into the build and the
 * console never fetches them. A fragment has no version: it is the upcoming release.
 */

export interface ChangelogEntry {
  /** The entry's file name without .json: what the unread dot remembers. */
  id: string;
  /** The release it shipped in; empty for an unreleased fragment. */
  version: string;
  date: string;
  title: string;
  description: string;
  tag: 'new' | 'improved' | 'fix';
  /** The release switch the feature waits behind; the entry shows only while it is on. */
  switch?: string;
}

export interface RoadmapItem {
  title: string;
  line: string;
}

const TAGS = new Set(['new', 'improved', 'fix']);

const RANK: Record<ChangelogEntry['tag'], number> = { new: 0, improved: 1, fix: 2 };

/** The upcoming release first, then versions newest first, then the history folded as `earlier`. */
function compareVersions(a: string, b: string): number {
  if (a === b) return 0;
  if (a === '') return -1;
  if (b === '') return 1;
  if (a === 'earlier') return 1;
  if (b === 'earlier') return -1;
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) if ((pa[i] ?? 0) !== (pb[i] ?? 0)) return (pb[i] ?? 0) - (pa[i] ?? 0);
  return 0;
}

/**
 * The entries by release, the upcoming one first and then newest first, and within a release new, improved, then fix,
 * each newest first (by date, then title); anything malformed is left out rather than breaking the popover, and
 * so is an entry whose release switch is off. `switches` are the console's (lib/api releaseSwitches); a switch not in
 * them counts as off, so a misspelt one never announces an unreleased feature.
 */
export function parseChangelog(source: string, switches: Readonly<Record<string, boolean>> = {}): ChangelogEntry[] {
  let raw: unknown;
  try {
    raw = JSON.parse(source);
  } catch {
    return [];
  }
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((e): e is ChangelogEntry => !!e && typeof e.id === 'string' && typeof e.title === 'string' && typeof e.date === 'string' && TAGS.has(e.tag))
    .filter((e) => e.switch === undefined || switches[e.switch] === true)
    .map(({ id, version, date, title, description, tag }) => ({ id, version: typeof version === 'string' ? version : '', date, title, description: description ?? '', tag }))
    .sort((a, b) => compareVersions(a.version, b.version) || RANK[a.tag] - RANK[b.tag] || b.date.localeCompare(a.date) || a.title.localeCompare(b.title));
}

export interface ChangelogRelease {
  /** Empty for the upcoming release. */
  version: string;
  date: string;
  /** New and improved entries, shown as rows. */
  changes: ChangelogEntry[];
  /** Fixes, shown as one collapsed line. */
  fixes: ChangelogEntry[];
}

/** The entries (already in `parseChangelog` order) grouped by release, fixes set apart. */
export function groupByRelease(entries: readonly ChangelogEntry[]): ChangelogRelease[] {
  const out: ChangelogRelease[] = [];
  for (const e of entries) {
    let group = out.find((g) => g.version === e.version);
    if (!group) out.push((group = { version: e.version, date: e.date, changes: [], fixes: [] }));
    (e.tag === 'fix' ? group.fixes : group.changes).push(e);
  }
  return out;
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
