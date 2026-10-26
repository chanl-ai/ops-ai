import { docs } from 'fumadocs-mdx:collections/server';
import type * as PageTree from 'fumadocs-core/page-tree';
import { type InferPageType, loader } from 'fumadocs-core/source';
import { createOpenAPI, openapiPlugin } from 'fumadocs-openapi/server';
import { icons } from 'lucide-react';
import { createElement } from 'react';

import { navMetas, siteTree } from './nav.mjs';
import { repoIndex, SITE_ROOTS } from './repo.mjs';

const root = repoIndex().root;

// One OpenAPI server per service, read from services/<service>/openapi.json in place.
const services = [...repoIndex().files]
  .filter((f) => /^services\/[^/]+\/openapi\.json$/.test(f))
  .map((f) => f.split('/')[1])
  .sort();

function apiGroup(apiPath: string) {
  const parts = apiPath.split('/').filter(Boolean);
  const seg = parts[0] === 'v1' || parts[0] === 'api' ? parts[1] : parts[0];
  return (seg ?? 'root').split(':')[0].replace(/[{}]/g, '').toLowerCase() || 'root';
}

// One OpenAPI server per service, so each service gets its own API reference folder.
const openapiServers = Object.fromEntries(
  services.map((s) => [s, createOpenAPI({ input: [`${root}/services/${s}/openapi.json`] })]),
);

const apiSources = await Promise.all(
  services.map((s) =>
    openapiServers[s].staticSource({
      baseDir: `services/${s}/api`,
      per: 'operation',
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      groupBy: (entry: any) => apiGroup(entry.item?.path ?? ''),
    }),
  ),
);

const docsSource = docs.toFumadocsSource();

export const source = loader({
  baseUrl: '/',
  source: {
    files: [
      ...docsSource.files,
      ...apiSources.flatMap((s) => s.files),
      ...navMetas(services.map((s) => `services/${s}/api`)),
    ],
  } as typeof docsSource,
  plugins: [openapiPlugin()],
  // docs/a/README.md is the page for /a; the two top pages follow SITE_ROOTS, so links and URLs agree.
  slugs(file, next) {
    const root = SITE_ROOTS[`docs/${file.path}`];
    if (root) return root.split('/').filter(Boolean);
    const slugs = next();
    if (slugs.at(-1)?.toLowerCase() === 'readme') return slugs.slice(0, -1);
    return slugs;
  },
});

export type Page = InferPageType<typeof source>;

// A lucide name from the sidebar list (`book-open`) to its icon; an unknown name fails the build instead of showing nothing.
function icon(name: string) {
  const key = name.replace(/(^|-)(\w)/g, (_, __, c: string) => c.toUpperCase()) as keyof typeof icons;
  if (!icons[key]) throw new Error(`docs sidebar: no lucide icon named "${name}"`);
  return createElement(icons[key]);
}

const built = siteTree(source.pageTree, icon);
// The build fails on a name SITE gives that no page has. A dev server reads the pages once at start, so a page added
// since reads as missing there: it warns instead of answering 500 on every route until restarted.
if (built.missing.length) {
  const message = `docs sidebar: SITE names pages or folders that do not exist: ${built.missing.join(', ')}`;
  if (process.env.NODE_ENV === 'development') console.warn(`${message} (restart the dev server after adding a page)`);
  else throw new Error(message);
}

/** The tree the sidebar shows: four tabs in journey order, built from SITE in nav.mjs. */
export const sidebarTree = built.tree as PageTree.Root;

// Fumadocs takes a tab's link from a page directly inside it, and every tab here holds only groups, so each tab links
// to its first page instead.
function firstUrl(nodes: PageTree.Node[]): string | undefined {
  for (const n of nodes) {
    if (n.type === 'page') return n.url;
    if (n.type === 'folder') {
      const url = n.index?.url ?? firstUrl(n.children);
      if (url) return url;
    }
  }
}

/** The tabs in the top bar, one per root folder of the sidebar tree. */
export const sidebarTabs = sidebarTree.children.flatMap((tab) =>
  tab.type === 'folder'
    ? [{ title: tab.name, description: tab.description, icon: tab.icon, url: firstUrl(tab.children) ?? '/', $folder: tab }]
    : [],
);
