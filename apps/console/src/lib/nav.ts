import type { Icon } from '@tabler/icons-react';
import { IconBolt, IconDatabase, IconGitPullRequest, IconHistory, IconHome, IconListDetails, IconMail, IconMessages, IconPlug, IconRobot, IconRocket, IconRoute, IconScale, IconSettings, IconShieldLock, IconUserCheck } from '@tabler/icons-react';

export interface NavItem {
  title: string;
  url: string;
  icon: Icon;
}

export interface NavGroup {
  label?: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    items: [
      { title: 'Overview', url: '/', icon: IconHome },
      { title: 'Cases', url: '/cases', icon: IconMail },
      // Chat sits with the day-to-day work surfaces; Agent Studio and Data Hub are where agents are configured.
      { title: 'Chat', url: '/chat', icon: IconMessages },
      // Reviews is daily work for approvers, so it sits with Cases and Chat rather than with configuration.
      { title: 'Reviews', url: '/reviews', icon: IconUserCheck },
    ],
  },
  {
    label: 'Agent Studio',
    items: [
      { title: 'Agents', url: '/agents', icon: IconRobot },
      { title: 'Workflows', url: '/workflows', icon: IconRoute },
      { title: 'Deployments', url: '/deployments', icon: IconRocket },
    ],
  },
  {
    label: 'Data Hub',
    items: [
      { title: 'Knowledge bases', url: '/knowledge', icon: IconDatabase },
      { title: 'Knowledge changes', url: '/knowledge/changes', icon: IconGitPullRequest },
      { title: 'Sources', url: '/sources', icon: IconPlug },
      { title: 'Tools & MCP', url: '/tools', icon: IconBolt },
    ],
  },
  // Oversight is its own job (risk, audit, platform admins), separate from building agents or curating data.
  { label: 'Govern', items: [{ title: 'Tool calls', url: '/logs/tool-calls', icon: IconListDetails }, { title: 'Audit log', url: '/logs/audit', icon: IconHistory }, { title: 'Access', url: '/access', icon: IconShieldLock }, { title: 'Model risk', url: '/model-risk', icon: IconScale }, { title: 'Settings', url: '/settings', icon: IconSettings }] },
];

/** The nav entry for a path. Longest matching url wins, so /knowledge/changes is not read as a knowledge base page. */
export function navMatch(pathname: string): { group: NavGroup; item: NavItem } | null {
  let best: { group: NavGroup; item: NavItem } | null = null;
  for (const group of NAV) {
    for (const item of group.items) {
      const hit = item.url === '/' ? pathname === '/' : pathname === item.url || pathname.startsWith(`${item.url}/`);
      if (hit && (!best || item.url.length > best.item.url.length)) best = { group, item };
    }
  }
  return best;
}

/** Breadcrumb trail for the header: section label, then the page title. */
export function crumbsFor(pathname: string): string[] {
  const best = navMatch(pathname);
  if (!best) return [];
  return best.group.label ? [best.group.label, best.item.title] : [best.item.title];
}
