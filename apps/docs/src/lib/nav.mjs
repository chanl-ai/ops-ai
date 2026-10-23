/**
 * The sidebar. Pages stay where they are in docs/, so every URL keeps working; the reader sees them through the tabs
 * and groups in SITE below, ordered as a developer meets them rather than as the repo files them.
 *
 * Two trees exist. The loader builds one from the folders (navMetas gives it titles and order, and it is where the
 * generated API pages land); siteTree() rebuilds the shown tree from SITE, taking pages and folders out of it.
 */
import { repoIndex } from './repo.mjs';

/**
 * Tabs, then groups, then entries. An entry is a page path relative to docs/ (a string, or { page, title, icon }), a
 * folder taken whole ({ folder, title, icon }), or the rest of a folder ({ rest }): every page under it that no other
 * entry places, keeping its subfolders. Icons are lucide names. Groups with `open` start expanded.
 */
export const SITE = [
  {
    tab: 'Docs',
    icon: 'book-open',
    description: 'Install, learn and build',
    groups: [
      {
        group: 'Get started',
        icon: 'rocket',
        open: true,
        entries: [
          { page: 'welcome.md', title: 'Welcome', icon: 'house' },
          { page: 'background/problem-statement.md', title: 'Why Ops AI', icon: 'lightbulb' },
          { page: 'guide/whats-built-today.md', icon: 'list-checks' },
          { page: 'guide/install.md', icon: 'download' },
        ],
      },
      {
        group: 'Concepts',
        icon: 'book',
        open: true,
        entries: [
          { page: 'guide/overview.md', icon: 'layout-grid' },
          { page: 'guide/how-work-flows.md', icon: 'workflow' },
          { page: 'guide/system-components.md', icon: 'boxes' },
          { page: 'guide/models.md', icon: 'cpu' },
          { page: 'guide/data-and-database.md', icon: 'database' },
          { page: 'guide/security-and-governance.md', icon: 'shield-check' },
        ],
      },
      {
        group: 'Build',
        icon: 'blocks',
        open: true,
        entries: [
          { page: 'console/agents-and-workflows.md', icon: 'bot' },
          {
            group: 'Workflows',
            icon: 'git-branch',
            entries: ['design/workflows/workflows-and-agents.md', 'design/workflows/workflow-nodes.md', 'design/workflows/canvas.md'],
          },
          {
            group: 'Tools and connections',
            icon: 'wrench',
            entries: ['design/tools/tool-system.md', 'design/tools/mcp-server.md'],
          },
          { page: 'design/human-tasks/task-page.md', title: 'Human tasks', icon: 'user-check' },
          { page: 'design/cases/case-page.md', title: 'Cases', icon: 'folder-kanban' },
          {
            group: 'Chat and channels',
            icon: 'message-square',
            entries: ['console/embedding-the-chat.md', 'design/chat/embedded-chat-screens.md'],
          },
        ],
      },
      {
        group: 'Deploy',
        icon: 'server',
        open: true,
        entries: [
          { page: 'guide/deployment-options.md', icon: 'map' },
          { page: 'guide/README.md', title: 'Client guide', icon: 'book-marked' },
          { page: 'deploy/install-guide.md', title: 'Install and operate, one page', icon: 'clipboard-list' },
          { page: 'deploy/install.md', title: 'The install script', icon: 'terminal' },
          { page: 'deploy/compose.md', title: 'Docker Compose', icon: 'container' },
          { page: 'deploy/kubernetes.md', title: 'Kubernetes', icon: 'ship-wheel' },
          { page: 'deploy/database.md', title: 'Database', icon: 'database-zap' },
          { page: 'guide/azure-sql.md', icon: 'database' },
          { page: 'deploy/release-package.md', title: 'Release package', icon: 'package' },
        ],
      },
      {
        group: 'Operate',
        icon: 'activity',
        open: true,
        entries: [
          { page: 'guide/operate.md', icon: 'activity' },
          { page: 'guide/support.md', icon: 'life-buoy' },
        ],
      },
    ],
  },
  {
    tab: 'API reference',
    icon: 'code',
    description: 'Every route of every service',
    groups: [
      { group: 'Start here', icon: 'flag', open: true, entries: [{ page: 'architecture/api.md', title: 'Conventions', icon: 'braces' }] },
      {
        group: 'HTTP API',
        icon: 'globe',
        open: true,
        entries: [
          { folder: 'services/platform-service/api', title: 'Platform', icon: 'shield' },
          { folder: 'services/agents-service/api', title: 'Agents and workflows', icon: 'bot' },
          { folder: 'services/tools-service/api', title: 'Tools', icon: 'wrench' },
          { folder: 'services/kb-service/api', title: 'Knowledge', icon: 'library' },
          { folder: 'services/files-service/api', title: 'Files', icon: 'file' },
          { folder: 'services/documents-service/api', title: 'Documents', icon: 'file-text' },
          { folder: 'services/models-service/api', title: 'Models (internal)', icon: 'cpu' },
        ],
      },
    ],
  },
  {
    tab: 'Architecture',
    icon: 'layers',
    description: 'How the platform is built and why',
    groups: [
      { group: 'Platform', icon: 'layout-grid', open: true, entries: [{ rest: 'architecture' }, 'diagrams/README.md'] },
      { group: 'Decision records', icon: 'scale', entries: [{ rest: 'architecture/decisions' }] },
      { group: 'Services', icon: 'server', entries: [{ rest: 'services' }] },
      { group: 'Design', icon: 'pen-tool', entries: [{ rest: 'design' }] },
    ],
  },
  {
    tab: 'Contributing',
    icon: 'hammer',
    description: 'Console screens, use cases and the team’s environments',
    groups: [
      { group: 'About these docs', icon: 'info', open: true, entries: [{ page: 'README.md', title: 'All documents', icon: 'list' }] },
      { group: 'Console', icon: 'monitor', entries: [{ rest: 'console' }] },
      { group: 'Use cases', icon: 'list-checks', entries: [{ rest: 'usecases' }] },
      { group: 'Libraries', icon: 'package', entries: [{ rest: 'packages' }] },
      {
        group: 'Team environments',
        icon: 'cloud',
        entries: ['deploy/fly.md', 'deploy/fly-staging.md', 'deploy/docs-site.md', 'deploy/demo-mailbox.md'],
      },
    ],
  },
];

const asEntry = (e) => (typeof e === 'string' ? { page: e } : e);

function* walkEntries(entries) {
  for (const raw of entries) {
    const e = asEntry(raw);
    if (e.group) yield* walkEntries(e.entries);
    else yield e;
  }
}

/** The pages the Docs tab names one by one: the reader-facing journey, held to the opening rule in check-links. */
export function docsTabPages() {
  return SITE[0].groups.flatMap((g) => [...walkEntries(g.entries)]).flatMap((e) => (e.page ? [e.page] : []));
}

const allEntries = () => SITE.flatMap((t) => t.groups.flatMap((g) => [...walkEntries(g.entries)]));
const under = (p, dir) => p === dir || p.startsWith(`${dir}/`);

/** Site pages (relative to docs/) that no tab places; the build fails on any, so a new page cannot drop out of view. */
export function unplacedPages(pagePaths) {
  const entries = allEntries();
  return pagePaths.filter(
    (p) =>
      !entries.some((e) => e.page === p || (e.folder && under(p, e.folder)) || (e.rest && under(p, e.rest))),
  );
}

/**
 * The tree the sidebar shows, built from SITE over the loader's folder tree. `icon` turns a lucide name into a node.
 * Returns the tree and the paths SITE names that the folder tree does not have, so a renamed page fails the build.
 */
export function siteTree(folderTree, icon) {
  const items = new Map();
  const folders = new Map();
  (function index(nodes) {
    for (const n of nodes) {
      if (n.type === 'page' && n.$ref) items.set(n.$ref, n);
      if (n.type === 'folder') {
        if (n.$ref?.folder) folders.set(n.$ref.folder, n);
        if (n.index?.$ref) items.set(n.index.$ref, n.index);
        index(n.children);
      }
    }
  })(folderTree.children);

  const entries = allEntries();
  const placed = new Set(entries.filter((e) => e.page).map((e) => e.page));
  const placedFolders = entries.filter((e) => e.folder).map((e) => e.folder);
  const missing = [];

  const page = (e) => {
    const node = items.get(e.page);
    if (!node) return missing.push(e.page), null;
    return { ...node, name: e.title ?? node.name, icon: e.icon ? icon(e.icon) : undefined };
  };
  // The rest of a folder: its pages and subfolders minus what SITE places elsewhere, empty subfolders dropped.
  const rest = (folder) => {
    const keep = (n) => {
      if (n.type === 'page') return !placed.has(n.$ref);
      if (n.type !== 'folder') return true;
      return !placedFolders.includes(n.$ref?.folder) && !SITE_RESTS.includes(n.$ref?.folder);
    };
    const prune = (n) => {
      if (n.type !== 'folder') return n;
      const children = n.children.filter(keep).map(prune).filter((c) => c.type !== 'folder' || c.children.length || c.index);
      const index = n.index && !placed.has(n.index.$ref) ? n.index : undefined;
      return { ...n, index, children, defaultOpen: false, collapsible: true };
    };
    const root = folders.get(folder);
    if (!root) return missing.push(folder), [];
    const pruned = prune(root);
    return [...(pruned.index ? [pruned.index] : []), ...pruned.children];
  };
  // Built folders need their own $id: Fumadocs keys sidebar rows and tabs by it.
  const build = (raw, open, parent) => {
    const e = asEntry(raw);
    if (e.group) {
      const $id = `${parent}/${e.group}`;
      return [{ $id, type: 'folder', name: e.group, icon: e.icon && icon(e.icon), defaultOpen: open, collapsible: true, children: e.entries.flatMap((c) => build(c, false, $id)) }];
    }
    if (e.page) return [page(e)].filter(Boolean);
    if (e.folder) {
      const f = folders.get(e.folder);
      if (!f) return missing.push(e.folder), [];
      return [{ ...f, name: e.title ?? f.name, icon: icon(e.icon), defaultOpen: false, collapsible: true }];
    }
    return rest(e.rest);
  };

  const children = SITE.map((t) => ({
    $id: `site:${t.tab}`,
    type: 'folder',
    root: true,
    name: t.tab,
    description: t.description,
    icon: icon(t.icon),
    children: t.groups.flatMap((g) => build(g, Boolean(g.open), `site:${t.tab}`)),
  }));
  return { tree: { name: folderTree.name, children }, missing };
}

const SITE_RESTS = allEntries()
  .filter((e) => e.rest)
  .map((e) => e.rest);

const TITLES = {
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
    const names = [...entries].filter((n) => n !== 'README');
    names.sort((a, b) => {
      if (a === 'api') return 1;
      if (b === 'api') return -1;
      return rank(dir, a) - rank(dir, b) || a.localeCompare(b);
    });
    const pagesList = [...(entries.has('README') ? ['README'] : []), ...names];
    metas.push({ type: 'meta', path: dir ? `${dir}/meta.json` : 'meta.json', data: { title: folderTitle(dir), pages: pagesList } });
  }
  for (const api of apiFolders) {
    metas.push({ type: 'meta', path: `${api}/meta.json`, data: { title: 'API reference' } });
  }
  return metas;
}
