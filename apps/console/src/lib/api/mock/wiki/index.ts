import type { WikiCollection, WikiPage, WikiPageDetail, WikiVersion, WikiView } from '@/lib/types/wiki';

import type { WikiApi } from '../../wiki-contract';
import { field, list, notFound, respond } from '../runtime';
import { inTeam } from '../teams';
import { COLLECTIONS, PAGES, VERIFY_EVERY_DAYS } from './seed';

const DAY = 86_400_000;
const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString();

/**
 * The Wiki over seeded pages. Verification is the only write: it stamps the current version with the caller and
 * clears the remembered and stale marks. Collection page counts are computed here, never in components.
 */
export function createWikiMock(deps: { me: string; kbNames: () => string[] }) {
  const pages = PAGES.map((s) => ({
    ...s,
    verifiedAt: s.verifiedDaysAgo === null ? null : ago(s.verifiedDaysAgo),
    verifiedBy: s.verifiedBy ?? null,
    updatedAt: ago(s.editedDaysAgo),
    versions: Array.from({ length: s.version }, (_, i): WikiVersion => {
      const v = s.version - i;
      return { version: v, at: ago(s.editedDaysAgo + i * 21), by: i === 0 ? s.editedBy : s.owner, note: v === 1 ? (s.provenance === 'remembered' ? `Remembered by ${s.origin}` : 'Created') : i === 0 && s.drift ? 'Synced from source' : 'Edited' };
    }),
  }));

  const row = (p: (typeof pages)[number]): WikiPage => ({ id: p.id, title: p.title, collection: p.collection, provenance: p.provenance, origin: p.origin, version: p.version, verifiedAt: p.verifiedAt, verifiedBy: p.verifiedBy, owner: p.owner, updatedAt: p.updatedAt, updatedBy: p.editedBy, citedBy: p.citedBy, drifted: !!p.drift });
  const detail = (p: (typeof pages)[number]): WikiPageDetail => ({ ...row(p), excerpt: p.excerpt, versions: p.versions, driftNote: p.drift });
  const needsVerification = (p: WikiPage) => !p.verifiedAt || Date.now() - new Date(p.verifiedAt).getTime() > VERIFY_EVERY_DAYS * DAY;
  const VIEW: Record<Exclude<WikiView, 'all'>, (p: WikiPage) => boolean> = { needs_verification: needsVerification, remembered: (p) => p.provenance === 'remembered', drifted: (p) => p.drifted };
  const scoped = () => pages.filter((p) => inTeam(p.owner)).map(row);
  const pageOr404 = (pid: string) => pages.find((p) => p.id === pid) ?? notFound('Page');

  const api: WikiApi = {
    list: (p) =>
      respond((m) => {
        const all = scoped();
        const inView = p.view === 'all' ? all : all.filter(VIEW[p.view]);
        const result = list(inView.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)), p, { text: (r) => `${r.title} ${r.collection} ${r.origin} ${r.owner}`, value: field, facetKeys: ['collection', 'provenance'] }, m);
        const src = m === 'empty' ? [] : all;
        return { ...result, viewCounts: { all: src.length, needs_verification: src.filter(needsVerification).length, remembered: src.filter(VIEW.remembered).length, drifted: src.filter(VIEW.drifted).length } };
      }),
    get: (pid) => respond(() => detail(pageOr404(pid))),
    verify: (pid) =>
      respond(() => {
        const p = pageOr404(pid);
        const at = new Date().toISOString();
        Object.assign(p, { verifiedAt: at, verifiedBy: deps.me });
        // A verified remembered page is ordinary content from now on; its origin stays on the first version.
        if (p.provenance === 'remembered') p.provenance = 'page';
        return detail(p);
      }),
    collections: () =>
      respond((m): WikiCollection[] => {
        if (m === 'empty') return [];
        const kbs = new Set(deps.kbNames());
        return COLLECTIONS.map((c) => ({ ...c, pages: pages.filter((p) => p.collection === c.name).length, knowledgeBases: c.knowledgeBases.filter((k) => kbs.has(k)) }));
      }),
  };
  return { api };
}
