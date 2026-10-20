import { docs } from 'fumadocs-mdx:collections/server';
import { type InferPageType, loader } from 'fumadocs-core/source';
import { createOpenAPI, openapiPlugin } from 'fumadocs-openapi/server';

import { navMetas } from './nav.mjs';
import { repoIndex } from './repo.mjs';

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
  // docs/a/README.md is the page for /a.
  slugs(file, next) {
    const slugs = next();
    if (slugs.at(-1)?.toLowerCase() === 'readme') return slugs.slice(0, -1);
    return slugs;
  },
});

export type Page = InferPageType<typeof source>;
