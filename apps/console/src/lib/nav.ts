import type { Icon } from '@tabler/icons-react';
import { PERSONAL_SETTINGS, SETTINGS_NAV } from './settings-tree';
import { IconChecklist, IconCpu, IconDatabase, IconFileSearch, IconFileText, IconFolder, IconHeartbeat, IconHistory, IconHome, IconInbox, IconKey, IconLayoutDashboard, IconList, IconListDetails, IconMail, IconMessage, IconMessages, IconPlayerPlay, IconPlugConnected, IconRobot, IconRoute, IconSettings, IconShield, IconShieldCheck, IconShieldLock, IconSparkles, IconTool, IconUserCheck, IconUsers, IconUserShield } from '@tabler/icons-react';

/** A page under its parent item: an indented row in the sidebar and an entry in the page-title switcher. */
export interface NavChild {
  title: string;
  url: string;
  /**
   * The roles-grid cell the page's own service checks, so the sidebar, the title switcher and search offer the page
   * only to who may open it. `everyTeam`: held in every team at once (a `*` role), as an account admin holds it.
   */
  needs?: NavNeed;
  /** The sub-row's icon, from the same @tabler set as the items. */
  icon?: Icon;
}

export interface NavNeed {
  area: string;
  action: string;
  everyTeam?: boolean;
}

export interface NavItem {
  title: string;
  url: string;
  icon: Icon;
  children?: NavChild[];
  /** Label of the parent's own tab in the section strip when it differs from the sidebar name (Brain's first tab is the knowledge bases list). */
  tabTitle?: string;
  /** The icon of the parent's own sub-row, when the parent shows one beside a lone child. */
  tabIcon?: Icon;
  /** Drawn as a row at the top of the sidebar rather than in its group; still matched for crumbs and search. */
  top?: boolean;
  /** What the parent page itself needs; a person who may open neither it nor any child is not offered the row. */
  needs?: NavNeed;
  /**
   * Two views of one thing reached from different sidebar rows (Connectors: Mine and Team setup): the title switcher
   * moves between them and the trail names the view, but neither is drawn as a sub-row.
   */
  views?: NavChild[];
}

/** platform-service reads the audit log for whoever holds audit.view in the team (GET /v1/audit). */
export const AUDIT_LOG: NavNeed = { area: 'audit', action: 'view' };
/** The gateway's call log names who called what: tools-service reads it under activity.view (GET /v1/executions). */
export const TOOL_CALL_LOG: NavNeed = { area: 'activity', action: 'view' };
/** The Activity list is read under the same cell as the tool-call log (agents-service GET /v1/activity). */
export const ACTIVITY: NavNeed = { area: 'activity', action: 'view' };
/** agents-service answers GET /v1/background only for an account admin: access.manage in every team. */
export const BACKGROUND: NavNeed = { area: 'access', action: 'manage', everyTeam: true };

/**
 * Connectors (owner, 8 November): one word for an app that acts for the team or the person, in two views. Mine is each
 * person's own sign-ins, the sidebar's top row "My connectors"; Team setup is where an admin turns apps on, the Data Hub
 * row "Connectors".
 */
export const CONNECTORS = 'Connectors';
export const CONNECTOR_VIEWS: NavChild[] = [
  { title: 'Mine', url: '/integrations/my-accounts', icon: IconUserCheck },
  { title: 'Team setup', url: '/integrations', icon: IconPlugConnected },
];

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    label: 'Work',
    items: [
      { title: 'Overview', url: '/', icon: IconHome, top: true },
      // The team's customer issues, with their deadlines and timelines; workflow runs are under Workflows.
      { title: 'Cases', url: '/cases', icon: IconMail },
      // Reviews is daily work for reviewers, so it sits with Cases and Chat rather than with configuration.
      { title: 'Human Tasks', url: '/reviews', icon: IconUserCheck },
      // Connectors, Mine: a person's own sign-ins, about the person rather than the team's data, visited whenever one
      // expires.
      { title: 'My connectors', url: '/integrations/my-accounts', icon: IconUserCheck, views: CONNECTOR_VIEWS },
      // Every conversation the person has had, searchable, beside the chat itself.
      { title: 'Chat', url: '/chat', icon: IconMessages, tabIcon: IconMessage, top: true, children: [{ title: 'Conversations', url: '/chat/conversations', icon: IconHistory }] },
    ],
  },
  {
    label: 'Agents',
    items: [
      { title: 'Agents', url: '/agents', icon: IconRobot },
      { title: 'Workflows', tabTitle: 'All workflows', url: '/workflows', icon: IconRoute, tabIcon: IconList, children: [{ title: 'Runs', url: '/workflows/runs', icon: IconPlayerPlay }] },
      // Where workflows hear from outside: the mailboxes an Email received trigger watches.
      { title: 'Channels', url: '/channels', icon: IconInbox },
      { title: 'Skills', url: '/skills', icon: IconSparkles },
      { title: 'Guardrails', url: '/guardrails', icon: IconShield },
      { title: 'Widgets', url: '/widgets', icon: IconLayoutDashboard },
    ],
  },
  {
    label: 'Data Hub',
    items: [
      // Wiki is hidden from the sidebar; its pages still answer at /wiki.
      // Knowledge bases decide what an agent searches and how; each KB page has its own tabs, so the row is flat.
      { title: 'Knowledge bases', url: '/knowledge', icon: IconDatabase },
      // Connectors, Team setup (the catalog), the secret values tools send and the tools, each its own item; an app's
      // auth configs are on its own page.
      { title: CONNECTORS, url: '/integrations', icon: IconPlugConnected, views: CONNECTOR_VIEWS },
      { title: 'Secrets', url: '/integrations/credentials', icon: IconKey },
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
      { title: 'Activity', tabTitle: 'Everything', url: '/activity', needs: ACTIVITY, icon: IconListDetails, tabIcon: IconList, children: [{ title: 'Tool calls', url: '/tools/calls', needs: TOOL_CALL_LOG, icon: IconTool }, { title: 'Audit log', url: '/logs/audit', needs: AUDIT_LOG, icon: IconFileSearch }, { title: 'Background', url: '/logs/background', needs: BACKGROUND, icon: IconHeartbeat }] },
      { title: 'Access', tabTitle: 'Members', url: '/access', icon: IconShieldLock, tabIcon: IconUsers, children: [{ title: 'Roles', url: '/access/roles', icon: IconUserShield }, { title: 'Tool access', url: '/access/tool-access', icon: IconKey }] },
      // Evals holds testing and governance evidence in one place; the model inventory is one view of it.
      { title: 'Evals', tabTitle: 'Suites', url: '/assurance', icon: IconShieldCheck, tabIcon: IconChecklist, children: [{ title: 'Model inventory', url: '/model-risk', icon: IconCpu }] },
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

export interface Crumb {
  label: string;
  /** Set when the crumb has its own page and is not the page shown, so a record page links back to its list. */
  href?: string;
}

/**
 * Breadcrumb trail for the header. Settings pages follow the settings sidebar (Settings, its group and section, the
 * page); other pages follow the app sidebar (section label, the item, then the tab when a child route matched).
 */
export function crumbsFor(pathname: string): Crumb[] {
  const link = (label: string, url: string): Crumb => (url === pathname ? { label } : { label, href: url });
  const personal = PERSONAL_SETTINGS.find((p) => p.href === pathname);
  if (personal) return [link('Settings', '/settings'), { label: personal.label }];
  const setting = [...SETTINGS_NAV].sort((a, b) => b.href.length - a.href.length).find((e) => pathname === e.href || pathname.startsWith(`${e.href}/`));
  if (setting) return [link('Settings', '/settings'), { label: setting.group }, ...(setting.section ? [{ label: setting.section }] : []), link(setting.title, setting.href)];
  const best = navMatch(pathname);
  if (!best) return [];
  // The first group's pages sit at the top of the sidebar under no heading, so their trail names no group.
  const group: Crumb[] = best.group === NAV[0] ? [] : [{ label: best.group.label }];
  // The top row already names its view (My connectors), so only the Data Hub row's trail adds it (Team setup).
  const view = best.item.views && best.group !== NAV[0] && viewFor(best.item.views, pathname);
  const crumbs: Crumb[] = [
    ...group,
    link(best.item.title, best.item.url),
    ...(best.child ? [link(best.child.title, best.child.url)] : view ? [link(view.title, view.url)] : []),
  ];
  // A group and its item can share a name (Agents › Agents); the trail names it once, keeping the item's link.
  return crumbs.filter((c, i) => c.label !== crumbs[i + 1]?.label);
}

/** The view a path is in: the longest matching url, so Mine (/integrations/my-accounts) is not also Team setup. */
function viewFor(views: NavChild[], pathname: string): NavChild | undefined {
  return [...views].sort((a, b) => b.url.length - a.url.length).find((v) => covers(v.url, pathname));
}

/** The pages grouped under one sidebar item, for the title switcher: the item's name, then the parent page and its children. Null when the item has no children. */
export function sectionFor(pathname: string): { label: string; pages: { href: string; label: string; icon?: Icon; needs?: NavNeed }[] } | null {
  const best = navMatch(pathname);
  if (best?.item.views) return { label: CONNECTORS, pages: best.item.views.map((v) => ({ href: v.url, label: v.title, icon: v.icon, needs: v.needs })) };
  if (!best?.item.children?.length) return null;
  return { label: best.item.title, pages: [{ href: best.item.url, label: best.item.tabTitle ?? best.item.title, icon: best.item.tabIcon, needs: best.item.needs }, ...best.item.children.map((c) => ({ href: c.url, label: c.title, icon: c.icon, needs: c.needs }))] };
}
