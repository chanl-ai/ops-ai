import type { Icon } from '@tabler/icons-react';
import { IconBook2, IconDatabase, IconFileText, IconFolder, IconHome, IconInbox, IconLayoutDashboard, IconListDetails, IconMail, IconMessages, IconPlugConnected, IconRobot, IconRoute, IconSettings, IconShield, IconShieldCheck, IconShieldLock, IconSparkles, IconTool, IconUserCheck } from '@tabler/icons-react';

/** A page under its parent item: an indented row in the sidebar and an entry in the page-title switcher. */
export interface NavChild {
  title: string;
  url: string;
  /** Shown only to a team admin: the page refuses everyone else (the audit log). */
  adminOnly?: boolean;
}

export interface NavItem {
  title: string;
  url: string;
  icon: Icon;
  children?: NavChild[];
  /** Label of the parent's own tab in the section strip when it differs from the sidebar name (Brain's first tab is the knowledge bases list). */
  tabTitle?: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    label: 'Work',
    items: [
      { title: 'Overview', url: '/', icon: IconHome },
      // The team's customer issues, with their deadlines and timelines (c-220); workflow runs are under Workflows.
      { title: 'Cases', url: '/cases', icon: IconMail },
      // Reviews is daily work for reviewers, so it sits with Cases and Chat rather than with configuration.
      { title: 'Human Tasks', url: '/reviews', icon: IconUserCheck },
      // Every conversation the person has had, searchable, beside the chat itself.
      { title: 'Chat', url: '/chat', icon: IconMessages, children: [{ title: 'Conversations', url: '/chat/conversations' }] },
    ],
  },
  {
    label: 'Agents',
    items: [
      { title: 'Agents', url: '/agents', icon: IconRobot },
      { title: 'Workflows', tabTitle: 'All workflows', url: '/workflows', icon: IconRoute, children: [{ title: 'Runs', url: '/workflows/runs' }] },
      // Where workflows hear from outside: the mailboxes an Email received trigger watches (c-199).
      { title: 'Channels', url: '/channels', icon: IconInbox },
      { title: 'Skills', url: '/skills', icon: IconSparkles },
      { title: 'Guardrails', url: '/guardrails', icon: IconShield },
      { title: 'Widgets', url: '/widgets', icon: IconLayoutDashboard },
    ],
  },
  {
    label: 'Data Hub',
    items: [
      // The Wiki holds the content agents read: pages, collections and the edits waiting on them.
      {
        title: 'Wiki',
        tabTitle: 'Pages',
        url: '/wiki',
        icon: IconBook2,
        children: [
          { title: 'Collections', url: '/wiki/collections' },
          { title: 'Changes', url: '/knowledge/changes' },
        ],
      },
      // Knowledge bases decide what an agent searches and how; each KB page has its own tabs, so the row is flat.
      { title: 'Knowledge bases', url: '/knowledge', icon: IconDatabase },
      // One row per system, with switches for syncing knowledge and exposing tools.
      { title: 'Connections', url: '/integrations', icon: IconPlugConnected },
      { title: 'Tools', url: '/tools', icon: IconTool },
      // Every file the platform stores, whatever brought it in (wiki, chat, mail, imports, exports), so it sits beside the Wiki rather than under it.
      { title: 'Files', url: '/files', icon: IconFolder },
      { title: 'Document types', url: '/document-types', icon: IconFileText },
    ],
  },
  // Oversight is its own job (risk, audit, platform admins), separate from building agents or curating data.
  {
    label: 'Govern',
    items: [
      // The one Activity list; tool calls keep their own page until they are an Activity kind.
      { title: 'Activity', tabTitle: 'Everything', url: '/activity', icon: IconListDetails, children: [{ title: 'Tool calls', url: '/logs/tool-calls' }, { title: 'Audit log', url: '/logs/audit', adminOnly: true }] },
      { title: 'Access', tabTitle: 'Members', url: '/access', icon: IconShieldLock, children: [{ title: 'Roles', url: '/access/roles' }, { title: 'Tool access', url: '/access/tool-access' }] },
      // Evals holds testing and governance evidence in one place; the model inventory is one view of it.
      { title: 'Evals', tabTitle: 'Suites', url: '/assurance', icon: IconShieldCheck, children: [{ title: 'Model inventory', url: '/model-risk' }] },
      { title: 'Settings', url: '/settings', icon: IconSettings },
    ],
  },
];

export interface NavHit {
  group: NavGroup;
  item: NavItem;
  child?: NavChild;
}

function covers(url: string, pathname: string): boolean {
  return url === '/' ? pathname === '/' : pathname === url || pathname.startsWith(`${url}/`);
}

/**
 * The nav entry for a path. Longest matching url across items and their children wins, so /knowledge/changes
 * resolves to Brain with the Changes child rather than to a knowledge base page.
 */
export function navMatch(pathname: string): NavHit | null {
  let best: (NavHit & { len: number }) | null = null;
  for (const group of NAV) {
    for (const item of group.items) {
      if (covers(item.url, pathname) && (!best || item.url.length > best.len)) best = { group, item, len: item.url.length };
      for (const child of item.children ?? []) {
        if (covers(child.url, pathname) && (!best || child.url.length > best.len)) best = { group, item, child, len: child.url.length };
      }
    }
  }
  return best && { group: best.group, item: best.item, child: best.child };
}

/** Breadcrumb trail for the header: section label, the sidebar item, then the tab when a child route matched. */
export function crumbsFor(pathname: string): string[] {
  const best = navMatch(pathname);
  if (!best) return [];
  const crumbs = best.child ? [best.group.label, best.item.title, best.child.title] : [best.group.label, best.item.title];
  // A group and its item can share a name (Agents › Agents); the trail names it once.
  return crumbs.filter((c, i) => c !== crumbs[i - 1]);
}

/** The pages grouped under one sidebar item, for the title switcher: the item's name, then the parent page and its children. Null when the item has no children. */
export function sectionFor(pathname: string): { label: string; pages: { href: string; label: string }[] } | null {
  const best = navMatch(pathname);
  if (!best?.item.children?.length) return null;
  return { label: best.item.title, pages: [{ href: best.item.url, label: best.item.tabTitle ?? best.item.title }, ...best.item.children.map((c) => ({ href: c.url, label: c.title }))] };
}
