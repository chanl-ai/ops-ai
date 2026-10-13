import type { Icon } from '@tabler/icons-react';
import { IconBook2, IconDatabase, IconHome, IconListDetails, IconMail, IconMessages, IconPlugConnected, IconRobot, IconRoute, IconSettings, IconShieldCheck, IconShieldLock, IconSparkles, IconTool, IconUserCheck } from '@tabler/icons-react';

/** A route shown as a tab under its parent item rather than as its own sidebar row. */
export interface NavChild {
  title: string;
  url: string;
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
      { title: 'Cases', url: '/cases', icon: IconMail },
      // Reviews is daily work for approvers, so it sits with Cases and Chat rather than with configuration.
      { title: 'Reviews', url: '/reviews', icon: IconUserCheck },
      { title: 'Chat', url: '/chat', icon: IconMessages },
    ],
  },
  {
    label: 'Agents',
    items: [
      { title: 'Agents', url: '/agents', icon: IconRobot },
      // A deployment only exists for a published workflow, so it lives under Workflows.
      { title: 'Workflows', url: '/workflows', icon: IconRoute, children: [{ title: 'Deployments', url: '/deployments' }] },
      { title: 'Skills', url: '/skills', icon: IconSparkles },
    ],
  },
  {
    label: 'Data Hub',
    items: [
      // The Wiki holds the content agents read: pages, documents, collections and the edits waiting on them.
      {
        title: 'Wiki',
        tabTitle: 'Pages',
        url: '/wiki',
        icon: IconBook2,
        children: [
          { title: 'Documents', url: '/files' },
          { title: 'Collections', url: '/wiki/collections' },
          { title: 'Changes', url: '/knowledge/changes' },
        ],
      },
      // Knowledge bases decide what an agent searches and how; each KB page has its own tabs, so the row is flat.
      { title: 'Knowledge bases', url: '/knowledge', icon: IconDatabase },
      // One row per system, with switches for syncing knowledge and exposing tools.
      { title: 'Connections', url: '/integrations', icon: IconPlugConnected },
      { title: 'Tools', url: '/tools', icon: IconTool },
    ],
  },
  // Oversight is its own job (risk, audit, platform admins), separate from building agents or curating data.
  {
    label: 'Govern',
    items: [
      { title: 'Activity', tabTitle: 'Tool calls', url: '/logs/tool-calls', icon: IconListDetails, children: [{ title: 'Audit log', url: '/logs/audit' }] },
      { title: 'Access', url: '/access', icon: IconShieldLock },
      // Evals holds testing and governance evidence in one place; the model inventory is one view of it.
      { title: 'Evals', url: '/assurance', icon: IconShieldCheck, children: [{ title: 'Model inventory', url: '/model-risk' }] },
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
  return best.child ? [best.group.label, best.item.title, best.child.title] : [best.group.label, best.item.title];
}

/** The pages grouped under one sidebar item, for the title switcher: the item's name, then the parent page and its children. Null when the item has no children. */
export function sectionFor(pathname: string): { label: string; pages: { href: string; label: string }[] } | null {
  const best = navMatch(pathname);
  if (!best?.item.children?.length) return null;
  return { label: best.item.title, pages: [{ href: best.item.url, label: best.item.tabTitle ?? best.item.title }, ...best.item.children.map((c) => ({ href: c.url, label: c.title }))] };
}
