/**
 * The sidebar, and the list of pages the site publishes. A page under docs/ is on the site only when SITE names it
 * (or a tab's `merging` list does); every other file under docs/ stays in the repository and a link to it opens on
 * GitHub. Pages stay where they are in docs/, so a published page keeps its URL.
 *
 * Two trees exist. The loader builds one from the folders (navMetas gives it titles and order, and it is where the
 * generated API pages land); siteTree() rebuilds the shown tree from SITE, taking pages and folders out of it.
 *
 * No imports: scripts at the repository root read SITE under plain node, without this app's dependencies.
 */

/**
 * Tabs, then groups, then entries. An entry is a page path relative to docs/ (a string, or { page, title, icon }) or
 * a generated API folder taken whole ({ folder, title, icon }). Icons are lucide names. Groups with `open` start
 * expanded.
 *
 * Docs, Deploy and operate, Security and Reference are for people using Ops AI; Contributing holds a short list of
 * pages on how the code is built. `public: true` marks the reader tabs, whose pages scripts/check-public-pages.mjs
 * holds to the reader-page rules. `merging` lists pages that are published and checked but have no sidebar row: each
 * is waiting to be merged into the page named in `into`.
 */
export const SITE = [
  {
    tab: 'Docs',
    icon: 'book-open',
    description: 'Learn Ops AI and build with it',
    public: true,
    groups: [
      {
        group: 'Get started',
        icon: 'rocket',
        open: true,
        entries: [
          { page: 'welcome.md', title: 'Welcome', icon: 'house' },
          { page: 'guide/quickstart.md', icon: 'zap' },
          { page: 'guide/overview.md', title: 'Core concepts', icon: 'layout-grid' },
          { page: 'guide/examples/coming-from-other-frameworks.md', title: 'Coming from another framework', icon: 'arrow-right-left' },
          { page: 'guide/glossary.md', title: 'Glossary', icon: 'book-a' },
        ],
      },
      {
        group: 'Build',
        icon: 'blocks',
        open: true,
        entries: [
          { page: 'guide/agents.md', icon: 'bot' },
          { page: 'guide/workflows.md', icon: 'git-branch' },
          { page: 'guide/human-tasks.md', title: 'Approvals and human tasks', icon: 'user-check' },
          { page: 'guide/cases.md', title: 'Cases', icon: 'folder-open' },
          { page: 'guide/knowledge.md', title: 'Knowledge', icon: 'library' },
          { page: 'guide/apps.md', title: 'Apps and tools', icon: 'app-window' },
          { page: 'guide/ops-assistant.md', title: 'Chat and channels', icon: 'message-square' },
          { page: 'guide/teams-and-access.md', title: 'Teams and roles', icon: 'users' },
        ],
      },
      {
        group: 'Guides',
        icon: 'briefcase',
        open: true,
        entries: [
          { page: 'guide/use-cases/card-disputes.md', title: 'Card disputes', icon: 'credit-card' },
          { page: 'guide/use-cases/answer-from-documents.md', title: 'Answer from your documents', icon: 'library' },
          { page: 'guide/use-cases/approve-a-write.md', title: 'Hold a write for approval', icon: 'hand' },
          { page: 'guide/use-cases/connect-an-app.md', title: 'Connect an app to an agent', icon: 'plug-zap' },
          { page: 'guide/build-your-first-tool.md', icon: 'wrench' },
          { page: 'console/embedding-the-chat.md', title: 'Put chat on your own pages', icon: 'messages-square' },
        ],
      },
      {
        group: 'Integrations',
        icon: 'plug',
        open: true,
        entries: [
          { page: 'guide/integrations/overview.md', title: 'Catalog', icon: 'plug' },
          { page: 'guide/integrations/salesforce.md', title: 'Salesforce', icon: 'cloud' },
          { page: 'guide/integrations/github.md', title: 'GitHub', icon: 'git-branch' },
          { page: 'guide/integrations/sharepoint.md', title: 'SharePoint', icon: 'folder-open' },
          { page: 'guide/integrations/confluence.md', title: 'Confluence', icon: 'book-open-text' },
          { page: 'guide/integrations/website.md', title: 'Website', icon: 'globe' },
          { page: 'guide/integrations/authentication.md', title: 'Authentication', icon: 'key-round' },
          { page: 'guide/integrations/build-a-plugin.md', title: 'Build a plugin', icon: 'package-plus' },
        ],
      },
    ],
    merging: [
      { page: 'guide/how-work-flows.md', into: 'guide/overview.md' },
      { page: 'guide/apps-setup.md', into: 'guide/apps.md' },
      { page: 'guide/models.md', into: 'guide/agents.md' },
      { page: 'guide/security-and-governance.md', into: 'guide/teams-and-access.md' },
      { page: 'guide/use-cases/chat-and-human-tasks.md', into: 'guide/human-tasks.md' },
      { page: 'guide/build-with-ops-ai.md', into: 'guide/build-your-first-tool.md' },
      { page: 'guide/examples/README.md', into: 'guide/agents.md' },
      { page: 'guide/examples/agents.md', into: 'guide/agents.md' },
      { page: 'guide/examples/skills.md', into: 'guide/agents.md' },
      { page: 'guide/examples/step-by-step-skills.md', into: 'guide/agents.md' },
      { page: 'guide/examples/workflows.md', into: 'guide/workflows.md' },
    ],
  },
  {
    tab: 'Deploy and operate',
    icon: 'server',
    description: 'Install, upgrade and run Ops AI',
    groups: [
      {
        group: 'Choose a deployment',
        icon: 'map',
        open: true,
        entries: [
          { page: 'deploy-and-operate.md', title: 'Deploy and operate', icon: 'server' },
          { page: 'guide/deployment-options.md', icon: 'map' },
          { page: 'guide/README.md', title: 'Client guide', icon: 'book-open' },
        ],
      },
      {
        group: 'Install',
        icon: 'download',
        open: true,
        entries: [
          { page: 'guide/install.md', icon: 'download' },
          { page: 'deploy/install.md', title: 'Install with the script', icon: 'terminal' },
          { page: 'deploy/compose.md', title: 'Docker Compose', icon: 'container' },
          { page: 'deploy/kubernetes.md', title: 'Kubernetes', icon: 'ship-wheel' },
          { page: 'deploy/release-package.md', title: 'Release package', icon: 'package' },
        ],
      },
      {
        group: 'Database',
        icon: 'database',
        open: true,
        entries: [
          { page: 'deploy/database.md', title: 'Database', icon: 'database-zap' },
          { page: 'guide/azure-sql.md', icon: 'database' },
          { page: 'guide/data-and-database.md', title: 'Where data is kept', icon: 'database' },
        ],
      },
      {
        group: 'Operate',
        icon: 'activity',
        open: true,
        entries: [
          { page: 'guide/operate.md', title: 'Operate', icon: 'activity' },
          { page: 'guide/system-components.md', icon: 'boxes' },
          { page: 'deploy/monitoring.md', title: 'Monitor', icon: 'activity' },
          { page: 'deploy/upgrade.md', title: 'Upgrade', icon: 'circle-arrow-up' },
          { page: 'deploy/backup-and-restore.md', title: 'Back up and restore', icon: 'archive' },
          { page: 'guide/plugins-install.md', title: 'Install and pin plugins', icon: 'package-plus' },
          { page: 'deploy/security-scanning.md', title: 'Security scanning', icon: 'scan-search' },
          { page: 'guide/support.md', icon: 'life-buoy' },
        ],
      },
    ],
  },
  {
    tab: 'Security',
    icon: 'shield-check',
    description: 'How Ops AI keeps teams, data and model calls under control',
    public: true,
    groups: [
      {
        group: 'Security review',
        icon: 'shield-check',
        open: true,
        entries: [
          { page: 'security/README.md', title: 'Security', icon: 'shield' },
          { page: 'security/tenancy-and-isolation.md', icon: 'building' },
          { page: 'security/identity-and-sign-in.md', icon: 'key-round' },
          { page: 'security/access-approvals-and-audit.md', icon: 'user-check' },
          { page: 'security/data-handling-and-masking.md', icon: 'eye-off' },
          { page: 'security/model-calls.md', icon: 'cpu' },
          { page: 'security/egress-and-connections.md', icon: 'globe-lock' },
        ],
      },
    ],
  },
  {
    tab: 'Reference',
    icon: 'code',
    description: 'HTTP API, SDKs, CLI, MCP and changes',
    public: true,
    groups: [
      { group: 'Start here', icon: 'flag', open: true, entries: [{ page: 'reference/README.md', title: 'Reference', icon: 'braces' }, { page: 'reference/http-api.md', icon: 'globe' }, { page: 'reference/cli.md', title: 'The opsai command line', icon: 'square-terminal' }, { page: 'reference/mcp.md', title: 'MCP', icon: 'plug' }, { page: 'guide/install-cli.md', title: 'Install the CLI', icon: 'download' }, { page: 'guide/whats-built-today.md', title: 'Feature status', icon: 'list-checks' }] },
      { group: 'Plugins', icon: 'puzzle', entries: [{ page: 'guide/plugins.md', title: 'Plugin manifest reference', icon: 'puzzle' }] },
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
        ],
      },
      {
        group: 'SDKs',
        icon: 'package',
        open: true,
        entries: [
          { page: 'sdk/python.md', title: 'Python', icon: 'file-code' },
          { page: 'sdk/typescript.md', title: 'TypeScript', icon: 'file-code' },
          { page: 'sdk/upgrading.md', title: 'Upgrading to 1.0.0', icon: 'circle-arrow-up' },
        ],
      },
      {
        group: 'Changelog',
        icon: 'clock',
        open: true,
        entries: [
          { page: 'guide/whats-new.md', icon: 'sparkles' },
          { page: 'sdk/changelog.md', title: 'SDK 1.0.0 changelog', icon: 'clock' },
        ],
      },
    ],
  },
  {
    tab: 'Contributing',
    icon: 'hammer',
    description: 'How Ops AI is built',
    groups: [
      {
        group: 'Start here',
        icon: 'flag',
        open: true,
        entries: [
          { page: 'contributing.md', title: 'Contributing', icon: 'hammer' },
          { page: 'README.md', title: 'All documents', icon: 'list' },
          { page: 'background/problem-statement.md', title: 'Requirements', icon: 'lightbulb' },
          { page: 'architecture/engineering-standards.md', title: 'Engineering standards', icon: 'ruler' },
        ],
      },
      {
        group: 'Architecture',
        icon: 'layers',
        open: true,
        entries: [
          'architecture/README.md',
          'architecture/enterprise-architecture.md',
          'architecture/service-map.md',
          'architecture/runtime.md',
          'architecture/data.md',
          'architecture/identity-and-tenancy.md',
        ],
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

const tabPages = (t) => [
  ...t.groups.flatMap((g) => [...walkEntries(g.entries)]).flatMap((e) => (e.page ? [e.page] : [])),
  ...(t.merging ?? []).map((m) => m.page),
];

/** The Docs tab's pages, held to the opening rule in check-links. */
export function docsTabPages() {
  return tabPages(SITE[0]);
}

/** Every page the site publishes, relative to docs/: the pages SITE names plus each tab's `merging` pages. */
export function sitePages() {
  return SITE.flatMap(tabPages);
}

/** The reader pages (relative to docs/): those in the tabs marked `public`, each with its tab's name. */
export function publicPages() {
  return SITE.filter((t) => t.public).flatMap((t) => tabPages(t).map((page) => ({ page, tab: t.tab })));
}

/** The pages of one tab, relative to docs/. */
export function pagesOfTab(tab) {
  return tabPages(SITE.find((t) => t.tab === tab));
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

  const missing = [];

  const page = (e) => {
    const node = items.get(e.page);
    if (!node) return missing.push(e.page), null;
    return { ...node, name: e.title ?? node.name, icon: e.icon ? icon(e.icon) : undefined };
  };
  // Built folders need their own $id: Fumadocs keys sidebar rows and tabs by it.
  const build = (raw, open, parent) => {
    const e = asEntry(raw);
    if (e.group) {
      const $id = `${parent}/${e.group}`;
      return [{ $id, type: 'folder', name: e.group, icon: e.icon && icon(e.icon), defaultOpen: open, collapsible: true, children: e.entries.flatMap((c) => build(c, false, $id)) }];
    }
    if (e.page) return [page(e)].filter(Boolean);
    const f = folders.get(e.folder);
    if (!f) return missing.push(e.folder), [];
    return [{ ...f, name: e.title ?? f.name, icon: icon(e.icon), defaultOpen: false, collapsible: true }];
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

function folderTitle(rel) {
  const name = rel.split('/').pop();
  if (/-service$/.test(name)) return name;
  const words = name.replace(/[-_]/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Meta files for every folder that holds site pages, plus the API folders `apiFolders` names. `order` is the order
 * docs/README.md lists pages in (repoIndex().order).
 */
export function navMetas(order, apiFolders = []) {
  const rels = sitePages();
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
  // An API folder's parents hold no site page of their own, so they are added here for the loader to title and order.
  for (const api of apiFolders) {
    const parts = api.split('/');
    for (let i = 0; i < parts.length; i++) {
      const dir = parts.slice(0, i).join('/');
      if (!folders.has(dir)) folders.set(dir, new Set());
      folders.get(dir).add(parts[i]);
    }
  }
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
