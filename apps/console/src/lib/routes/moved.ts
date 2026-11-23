/**
 * Old console addresses and where each one lives now that every page sits under its area (Work, Build, Data,
 * Govern). Bookmarks, emails, run cards and links stored in data still carry the old addresses, so the proxy sends
 * each one to its new home with the rest of the path and the query kept. Longest prefix first: /tools/calls is not
 * /tools.
 */
export const MOVED: readonly (readonly [string, string])[] = [
  ['/settings/account/connectors', '/work/apps'],
  ['/integrations/my-accounts', '/work/apps'],
  ['/integrations/credentials', '/data/secrets'],
  ['/integrations/sources', '/data/sources'],
  ['/integrations/apps', '/data/connectors'],
  ['/workflows/batches', '/build/runs/batches'],
  ['/knowledge/changes', '/data/changes'],
  ['/logs/background', '/govern/activity/background'],
  ['/logs/tool-calls', '/govern/activity/tool-calls'],
  ['/document-types', '/data/document-types'],
  ['/workflows/runs', '/build/runs'],
  ['/integrations', '/data/connectors'],
  ['/reviews/all', '/govern/reviews'],
  ['/tools/calls', '/govern/activity/tool-calls'],
  ['/logs/audit', '/govern/activity/audit'],
  ['/model-risk', '/govern/models'],
  ['/guardrails', '/build/guardrails'],
  ['/assurance', '/govern/evals'],
  ['/knowledge', '/data/knowledge'],
  ['/workflows', '/build/workflows'],
  ['/channels', '/build/channels'],
  ['/activity', '/govern/activity'],
  ['/policies', '/govern/policies'],
  ['/reviews', '/work/tasks'],
  ['/widgets', '/build/widgets'],
  ['/agents', '/build/agents'],
  ['/access', '/govern/access'],
  ['/skills', '/build/skills'],
  ['/files', '/data/files'],
  ['/tools', '/data/tools'],
  ['/cases', '/work/cases'],
  ['/wiki', '/data/wiki'],
];

/** The new address for an old path, or null when the path did not move. */
// Old addresses whose own page moved apart from the pages under it: the sources list now sits in Knowledge, while a
// source's page stays at /data/sources/<id>.
const MOVED_EXACT: Readonly<Record<string, string>> = { '/integrations/sources': '/data/knowledge' };

export function movedTo(pathname: string): string | null {
  const exact = MOVED_EXACT[pathname];
  if (exact) return exact;
  for (const [from, to] of MOVED) {
    if (pathname === from || pathname.startsWith(`${from}/`)) return to + pathname.slice(from.length);
  }
  return null;
}
