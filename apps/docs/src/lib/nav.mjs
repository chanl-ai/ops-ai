/**
 * The sidebar order, as virtual meta files: docs/ holds no meta.json, so the order comes from docs/README.md (pages
 * in the order its tables list them) and the section list below.
 */
import { repoIndex } from './repo.mjs';

const ROOT_PAGES = [
  'README',
  'background',
  'guide',
  '---Architecture---',
  '...architecture',
  '---Design---',
  '...design',
  '---Deploy and install---',
  '...deploy',
  '---Console---',
  '...console',
  '---Services and API reference---',
  '...services',
  'packages',
  '---Use cases---',
  '...usecases',
];
const TITLES = {
  background: 'Background',
  guide: 'Guide',
  'architecture/decisions': 'Decision records',
  'design/workflows': 'Workflows and agents',
  'design/tools': 'Tools',
  'design/human-tasks': 'Human tasks',
  'design/cases': 'Cases',
  'design/chat': 'Chat',
  'design/data': 'Data',
  'design/research': 'Research',
  'console/approved': 'Approved screens',
  'console/proposed': 'Proposed screens',
  packages: 'Libraries',
};
const DESIGN_ORDER = ['workflows', 'tools', 'human-tasks', 'cases', 'chat', 'data', 'research'];

function folderTitle(rel) {
  if (TITLES[rel]) return TITLES[rel];
  const name = rel.split('/').pop();
  if (/-service$/.test(name) || name.startsWith('ops_') || name.includes('runner')) return name;
  const words = name.replace(/[-_]/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Meta files for every folder that holds site pages, plus the API folders `apiFolders` names. */
export function navMetas(apiFolders = []) {
  const { pages, order } = repoIndex();
  const rels = Object.keys(pages).map((p) => p.slice('docs/'.length));
  const folders = new Map(); // folder -> Set of entries (page names and subfolder names)
  for (const rel of rels) {
    const parts = rel.split('/');
    for (let i = 0; i < parts.length; i++) {
      const dir = parts.slice(0, i).join('/');
      const entry = i === parts.length - 1 ? parts[i].replace(/\.md$/, '') : parts[i];
      if (!folders.has(dir)) folders.set(dir, new Set());
      folders.get(dir).add(entry);
    }
  }
  for (const api of apiFolders) folders.get(api.split('/').slice(0, -1).join('/'))?.add('api');
  const rank = (dir, name) => {
    const prefix = dir ? `${dir}/${name}` : name;
    const i = order.findIndex((p) => p === `${prefix}.md` || p.startsWith(`${prefix}/`));
    return i === -1 ? Number.POSITIVE_INFINITY : i;
  };
  const metas = [];
  for (const [dir, entries] of folders) {
    if (!dir) {
      metas.push({ type: 'meta', path: 'meta.json', data: { pages: ROOT_PAGES } });
      continue;
    }
    const names = [...entries].filter((n) => n !== 'README');
    names.sort((a, b) => {
      if (a === 'api') return 1;
      if (b === 'api') return -1;
      if (dir === 'design') return DESIGN_ORDER.indexOf(a) - DESIGN_ORDER.indexOf(b);
      return rank(dir, a) - rank(dir, b) || a.localeCompare(b);
    });
    const pagesList = [...(entries.has('README') ? ['README'] : []), ...names];
    metas.push({ type: 'meta', path: `${dir}/meta.json`, data: { title: folderTitle(dir), pages: pagesList } });
  }
  for (const api of apiFolders) {
    metas.push({ type: 'meta', path: `${api}/meta.json`, data: { title: 'API reference' } });
  }
  return metas;
}
