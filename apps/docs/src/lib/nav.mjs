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
 *
 * Docs, Deploy and operate, Security and Reference are for people using Ops AI; how the code is built goes in
 * Contributing. `public: true` marks the tabs whose pages scripts/check-public-pages.mjs holds to the user-page rules.
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
          { page: 'background/problem-statement.md', title: 'Why Ops AI', icon: 'lightbulb' },
          { page: 'guide/quickstart.md', icon: 'zap' },
          { page: 'guide/install-cli.md', title: 'Install the CLI', icon: 'square-terminal' },
          { page: 'guide/whats-built-today.md', icon: 'list-checks' },
        ],
      },
      {
        group: 'Concepts',
        icon: 'book',
        open: true,
        entries: [
          { page: 'guide/overview.md', icon: 'layout-grid' },
          { page: 'guide/how-work-flows.md', icon: 'workflow' },
          { page: 'guide/agents.md', icon: 'bot' },
          { page: 'guide/workflows.md', icon: 'git-branch' },
          { page: 'guide/schedule-a-workflow.md', icon: 'calendar-clock' },
          { page: 'guide/edit-a-workflow-step.md', title: 'Open a workflow step', icon: 'mouse-pointer-click' },
          { page: 'guide/apps.md', title: 'Tools and apps', icon: 'app-window' },
          { page: 'guide/ops-assistant.md', title: 'Chat and channels', icon: 'message-square' },
          { page: 'guide/knowledge.md', title: 'Knowledge', icon: 'library' },
          { page: 'guide/human-tasks.md', title: 'Human tasks and approvals', icon: 'user-check' },
          { page: 'guide/cases.md', title: 'Cases', icon: 'folder-open' },
          { page: 'guide/teams-and-access.md', title: 'Teams and access', icon: 'users' },
          { page: 'guide/security-and-governance.md', title: 'Governance', icon: 'shield-check' },
          { page: 'guide/models.md', title: 'Models', icon: 'cpu' },
          { page: 'console/embedding-the-chat.md', title: 'Chat on your own pages', icon: 'messages-square' },
        ],
      },
      {
        group: 'Guides by use case',
        icon: 'briefcase',
        open: true,
        entries: [
          { page: 'guide/use-cases/card-disputes.md', title: 'Card disputes', icon: 'credit-card' },
          { page: 'guide/use-cases/chat-and-human-tasks.md', title: 'Start the day from chat', icon: 'message-square' },
          { page: 'guide/use-cases/answer-from-documents.md', title: 'Answer from your documents', icon: 'library' },
          { page: 'guide/use-cases/approve-a-write.md', title: 'Hold a write for approval', icon: 'hand' },
          { page: 'guide/use-cases/connect-an-app.md', title: 'Connect an app to an agent', icon: 'plug-zap' },
          { page: 'guide/build-with-ops-ai.md', icon: 'blocks' },
          { page: 'guide/build-your-first-tool.md', icon: 'wrench' },
        ],
      },
      {
        group: 'Examples',
        icon: 'code',
        open: true,
        entries: [
          { page: 'guide/examples/README.md', title: 'Examples for builders', icon: 'list' },
          { page: 'guide/examples/agents.md', icon: 'bot' },
          { page: 'guide/examples/skills.md', icon: 'sparkles' },
          { page: 'guide/examples/workflows.md', icon: 'git-branch' },
          { page: 'guide/examples/step-by-step-skills.md', icon: 'list-ordered' },
          { page: 'guide/examples/coming-from-other-frameworks.md', icon: 'arrow-right-left' },
        ],
      },
      {
        group: 'Integrations',
        icon: 'plug',
        open: true,
        entries: [
          { page: 'guide/integrations/overview.md', title: 'Integrations', icon: 'plug' },
          { page: 'guide/apps-setup.md', title: 'Set up an app', icon: 'settings' },
          { page: 'guide/integrations/salesforce.md', title: 'Salesforce', icon: 'cloud' },
          { page: 'guide/integrations/github.md', title: 'GitHub', icon: 'git-branch' },
          { page: 'guide/integrations/sharepoint.md', title: 'SharePoint and OneDrive', icon: 'folder-open' },
          { page: 'guide/integrations/confluence.md', title: 'Confluence', icon: 'book-open-text' },
          { page: 'guide/integrations/website.md', title: 'Website', icon: 'globe' },
          { page: 'guide/integrations/sign-in-oauth.md', title: 'Sign in with OAuth', icon: 'log-in' },
          { page: 'guide/integrations/sign-in-keys.md', title: 'Sign in with a key or password', icon: 'key-round' },
          { page: 'guide/integrations/sign-in-certificates.md', title: 'Sign in with a certificate', icon: 'file-badge' },
          { page: 'guide/integrations/build-a-plugin.md', title: 'Build a plugin', icon: 'package-plus' },
        ],
      },
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
          { page: 'security/recovery-and-redrive.md', icon: 'rotate-ccw' },
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
      { group: 'Start here', icon: 'flag', open: true, entries: [{ page: 'reference/README.md', title: 'Reference', icon: 'braces' }, { page: 'reference/http-api.md', icon: 'globe' }, { page: 'reference/cli.md', title: 'The opsai command line', icon: 'square-terminal' }, { page: 'reference/mcp.md', title: 'MCP', icon: 'plug' }] },
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
    description: 'How Ops AI is built, tested and released',
    groups: [
      {
        group: 'Start here',
        icon: 'flag',
        open: true,
        entries: [
          { page: 'contributing.md', title: 'Contributing', icon: 'hammer' },
          { page: 'README.md', title: 'All documents', icon: 'list' },
        ],
      },
      {
        group: 'Architecture',
        icon: 'layers',
        open: true,
        entries: [
          {
            group: 'Overview',
            icon: 'layout-grid',
            entries: [
              'architecture/README.md',
              'architecture/enterprise-architecture.md',
              'architecture/service-map.md',
              'architecture/platform-choices.md',
              'architecture/words-and-entities.md',
              'architecture/dependencies.md',
              'architecture/delivery.md',
              'diagrams/README.md',
            ],
          },
          {
            group: 'Runtime and workflows',
            icon: 'workflow',
            entries: [
              'architecture/runtime.md',
              'architecture/workflow-runner.md',
              'architecture/definitions-and-versions.md',
              'architecture/workflows-as-tools.md',
              'architecture/templates.md',
              'architecture/agent-guardrails.md',
              'architecture/human-in-the-loop.md',
              'architecture/durability-failure-and-audit.md',
            ],
          },
          {
            group: 'Identity and access',
            icon: 'key-round',
            entries: [
              'architecture/identity-and-tenancy.md',
              'architecture/roles-and-permissions.md',
              'architecture/saml-sign-in.md',
              'architecture/app-accounts.md',
            ],
          },
          {
            group: 'Tools, channels and chat',
            icon: 'wrench',
            entries: [
              'architecture/api.md',
              'architecture/tool-lifecycle.md',
              'architecture/integrations.md',
              'architecture/mcp.md',
              'architecture/channels-and-deployments.md',
              'architecture/chat-widgets.md',
              'architecture/embedded-chat.md',
              'architecture/console-areas.md',
            ],
          },
          {
            group: 'Data',
            icon: 'database',
            entries: ['architecture/data.md', 'architecture/data-model.md', 'architecture/knowledge-base.md', 'architecture/logging-and-data-writes.md'],
          },
          {
            group: 'Operations',
            icon: 'activity',
            entries: ['architecture/operations.md', 'architecture/make.md', 'architecture/cloud-boxes.md'],
          },
          { group: 'Decision records', icon: 'scale', entries: [{ rest: 'architecture/decisions' }] },
          // Anything added to architecture/ without a group above still shows, here, rather than failing the build.
          { rest: 'architecture' },
        ],
      },
      {
        group: 'Engineering standards',
        icon: 'ruler',
        entries: [
          { page: 'architecture/engineering-standards.md', title: 'Engineering standards', icon: 'ruler' },
          { rest: 'architecture/standards' },
          { group: 'Migration to the standards', icon: 'route', entries: ['architecture/migration/api-changes.md'] },
        ],
      },
      { group: 'Services', icon: 'server', entries: [{ rest: 'services' }] },
      { group: 'Packages', icon: 'package', entries: ['packages/README.md', { rest: 'packages' }] },
      {
        group: 'Use-case test catalogue',
        icon: 'list-checks',
        entries: [
          { rest: 'usecases' },
          {
            group: 'Example coverage',
            icon: 'table',
            entries: ['guide/workflow-example-coverage.md', 'guide/agent-example-coverage.md', 'guide/developer-surface-coverage.md'],
          },
        ],
      },
      {
        group: 'Design proposals',
        icon: 'pen-tool',
        entries: [
          'design/README.md',
          { page: 'sdk/changelog-next-major.md', title: 'SDK 1.0.0 route-by-route record', icon: 'clock' },
          { page: 'console/agents-and-workflows.md', title: 'Agents and workflows in the console', icon: 'monitor' },
          { rest: 'design' },
          { group: 'Console', icon: 'monitor', entries: [{ rest: 'console' }] },
        ],
      },
      { group: 'Agent skills', icon: 'sparkles', entries: [{ rest: 'guide/skills' }] },
      {
        group: 'Release process',
        icon: 'tag',
        entries: [
          'deploy/release.md',
          { page: 'deploy/install-guide.md', title: 'Install guide, one page (generated)', icon: 'clipboard-list' },
          { page: 'deploy/package-install.md', title: 'INSTALL.md inside the release package', icon: 'package' },
          'deploy/docs-site.md',
          {
            group: 'Team environments',
            icon: 'cloud',
            entries: ['deploy/devhost.md', 'deploy/fly.md', 'deploy/fly-staging.md', 'deploy/demo-mailbox.md'],
          },
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

/** The pages the Docs tab names one by one: the reader-facing journey, held to the opening rule in check-links. */
export function docsTabPages() {
  return SITE[0].groups.flatMap((g) => [...walkEntries(g.entries)]).flatMap((e) => (e.page ? [e.page] : []));
}

/**
 * The pages (relative to docs/) that the tabs marked `public` show, resolving folder and rest entries over
 * `pagePaths`. A page another tab places by name stays with that tab.
 */
export function publicPages(pagePaths) {
  const named = new Map();
  for (const t of SITE) for (const g of t.groups) for (const e of walkEntries(g.entries)) if (e.page) named.set(e.page, t);
  return pagePaths.filter((p) => {
    const owner = named.get(p) ?? SITE.find((t) => t.groups.some((g) => [...walkEntries(g.entries)].some((e) => (e.folder && under(p, e.folder)) || (e.rest && under(p, e.rest)))));
    return Boolean(owner?.public);
  });
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
