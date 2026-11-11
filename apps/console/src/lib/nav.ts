import type { Icon } from '@tabler/icons-react';
import { PERSONAL_SETTINGS, SETTINGS_NAV } from './settings-tree';
import { IconChecklist, IconCpu, IconGavel, IconDatabase, IconFileSearch, IconFileText, IconFolder, IconHeartbeat, IconHistory, IconHome, IconInbox, IconKey, IconLayoutDashboard, IconList, IconListDetails, IconMail, IconMessage, IconMessages, IconPlayerPlay, IconPlugConnected, IconRobot, IconRoute, IconSettings, IconShield, IconShieldCheck, IconShieldLock, IconSparkles, IconTool, IconUserCheck, IconUsers, IconUserShield } from '@tabler/icons-react';

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
  /** No sidebar row: the entry gives its routes an area, a trail and a place in search (My connectors is in the user menu). */
  hidden?: boolean;
  /** Other routes that belong to this entry's area and trail without a row of their own (a page reached from a record or a link). */
  also?: string[];
  /** Other cells that also offer the row: a person who holds any one of them sees it. */
  or?: NavNeed[];
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
 * person's own sign-ins, the user menu's "My connectors"; Team setup is where an admin turns apps on, the Data
 * row "Connectors".
 */
export const CONNECTORS = 'Connectors';
/** Mine's one name, on the sidebar row, its page title and the avatar menu. */
export const MY_CONNECTORS = 'My connectors';
export const CONNECTOR_VIEWS: NavChild[] = [
  { title: 'Mine', url: '/integrations/my-accounts', icon: IconUserCheck },
  { title: 'Team setup', url: '/integrations', icon: IconPlugConnected },
];

/** The four areas the sidebar shows one at a time, in the order the header offers them and ⌘1 to ⌘4 reach them. */
export const AREAS = ['Work', 'Build', 'Data', 'Govern'] as const;
export type AreaName = (typeof AREAS)[number];

export interface NavGroup {
  label: AreaName;
  items: NavItem[];
}

const cell = (area: string, action: string): NavNeed => ({ area, action });
/** The Settings pages and Policies are offered on settings: view, which the Security team holds. */
export const SETTINGS_VIEW: NavNeed = cell('settings', 'view');
/** The Overview is offered to anyone who has work to look at: cases, Human Tasks or workflow runs. */
export const OVERVIEW_NEEDS: NavNeed[] = [cell('cases', 'view'), cell('reviews', 'view'), cell('workflows', 'view')];

export const NAV: NavGroup[] = [
  {
    label: 'Work',
    items: [
      { title: 'Overview', url: '/', icon: IconHome, needs: OVERVIEW_NEEDS[0], or: OVERVIEW_NEEDS.slice(1) },
      // The team's customer issues, with their deadlines and timelines; workflow runs are under Workflows.
      { title: 'Cases', url: '/cases', icon: IconMail, needs: cell('cases', 'view') },
      // Reviews is daily work for reviewers, so it sits with Cases and Chat rather than with configuration.
      { title: 'Human Tasks', url: '/reviews', icon: IconUserCheck, needs: cell('reviews', 'view') },
      // Connectors, Mine: a person's own sign-ins. Its row is in the user menu; the entry stays so the page has an area.
      { title: MY_CONNECTORS, url: '/integrations/my-accounts', icon: IconUserCheck, hidden: true, views: CONNECTOR_VIEWS },
      // The sidebar draws this as New chat and the Chats group; All chats lists every conversation the person has had.
      { title: 'Chat', url: '/chat', icon: IconMessages, tabIcon: IconMessage, hidden: true, needs: cell('chat', 'run'), children: [{ title: 'All chats', url: '/chat/conversations', icon: IconHistory }] },
    ],
  },
  {
    label: 'Build',
    items: [
      { title: 'Agents', url: '/agents', icon: IconRobot, needs: cell('agents', 'view'), also: ['/prompt-blocks'] },
      { title: 'Workflows', tabTitle: 'All workflows', url: '/workflows', icon: IconRoute, tabIcon: IconList, needs: cell('workflows', 'view'), children: [{ title: 'Runs', url: '/workflows/runs', icon: IconPlayerPlay }] },
      // Where workflows hear from outside: the mailboxes an Email received trigger watches.
      { title: 'Channels', url: '/channels', icon: IconInbox, needs: cell('deployments', 'view'), also: ['/deployments'] },
      { title: 'Skills', url: '/skills', icon: IconSparkles, needs: cell('skills', 'view') },
      { title: 'Guardrails', url: '/guardrails', icon: IconShield, needs: cell('guardrails', 'view') },
      { title: 'Widgets', url: '/widgets', icon: IconLayoutDashboard, needs: cell('widgets', 'view') },
      { title: 'Tools', url: '/tools', icon: IconTool, needs: cell('tools', 'view') },
    ],
  },
  {
    label: 'Data',
    items: [
      // Knowledge bases decide what an agent searches and how; each KB page has its own tabs, so the row is flat.
      { title: 'Knowledge bases', url: '/knowledge', icon: IconDatabase, needs: cell('knowledge', 'view'), also: ['/sources', '/wiki'] },
      // Connectors, Team setup (the catalog); an app's auth configs are on its own page.
      { title: CONNECTORS, url: '/integrations', icon: IconPlugConnected, needs: cell('connections', 'view'), views: CONNECTOR_VIEWS, also: ['/connect', '/tools/connections'] },
      { title: 'Secrets', url: '/integrations/credentials', icon: IconKey, needs: cell('secrets_egress', 'view') },
      // Every file the platform stores, whatever brought it in (wiki, chat, mail, imports, exports).
      { title: 'Files', url: '/files', icon: IconFolder, needs: cell('files', 'view') },
      { title: 'Document types', url: '/document-types', icon: IconFileText, needs: cell('documents', 'view') },
    ],
  },
  // Oversight is its own job (risk, audit, platform admins), separate from building agents or curating data.
  {
    label: 'Govern',
    items: [
      // The one Activity list; tool calls keep their own page until they are an Activity kind.
      { title: 'Activity', tabTitle: 'Everything', url: '/activity', needs: ACTIVITY, icon: IconListDetails, tabIcon: IconList, children: [{ title: 'Tool calls', url: '/tools/calls', needs: TOOL_CALL_LOG, icon: IconTool }, { title: 'Audit log', url: '/logs/audit', needs: AUDIT_LOG, icon: IconFileSearch }, { title: 'Background', url: '/logs/background', needs: BACKGROUND, icon: IconHeartbeat }] },
      // Every review of every team, past and present; Human Tasks under Work is the queue waiting for the person.
      { title: 'Reviews', url: '/reviews/all', icon: IconChecklist, needs: cell('reviews', 'view'), also: ['/reviews/policies'] },
      { title: 'Access', tabTitle: 'Members', url: '/access', needs: cell('access', 'view'), icon: IconShieldLock, tabIcon: IconUsers, children: [{ title: 'Roles', url: '/access/roles', icon: IconUserShield }, { title: 'Tool access', url: '/access/tool-access', icon: IconKey }] },
      // Any member reads the policies; the row is for who sets up the workspace, as Settings is.
      { title: 'Policies', url: '/policies', icon: IconGavel, needs: SETTINGS_VIEW, or: [cell('access', 'manage')] },
      // Evals holds testing and governance evidence in one place; the model inventory is one view of it.
      { title: 'Evals', tabTitle: 'Suites', url: '/assurance', icon: IconShieldCheck, tabIcon: IconChecklist, needs: cell('agents', 'decide'), children: [{ title: 'Model inventory', url: '/model-risk', icon: IconCpu }] },
      // A team admin who lacks settings: view still reaches the team's settings through access: manage.
      { title: 'Settings', url: '/settings', icon: IconSettings, needs: SETTINGS_VIEW, or: [cell('access', 'manage')], also: ['/account'] },
    ],
  },
];

/** A row is offered when its own cell, an alternative cell or any child page is open to the person. Undefined cells (still loading) offer nothing. */
export type Allows = (needs?: NavNeed) => boolean | undefined;
export function itemOffered(allows: Allows, item: NavItem): boolean {
  return ownOffered(allows, item) || childrenOffered(allows, item).length > 0;
}

function ownOffered(allows: Allows, item: NavItem): boolean {
  return allows(item.needs) === true || (item.or ?? []).some((n) => allows(n) === true);
}

/** A child page is offered on its own cell, or on its parent's when it names none (Runs is open to who may open Workflows). */
export function childrenOffered(allows: Allows, item: NavItem): NavChild[] {
  return (item.children ?? []).filter((c) => (c.needs ? allows(c.needs) === true : ownOffered(allows, item)));
}

/** The rows of an area the person may open: every item that draws a row. */
export function rowsOfArea(area: AreaName, allows: Allows): NavItem[] {
  return NAV.find((g) => g.label === area)!.items.filter((i) => !i.hidden && itemOffered(allows, i));
}

/** The areas the person has a page in, in header order. */
export function offeredAreas(allows: Allows): AreaName[] {
  return AREAS.filter((a) => rowsOfArea(a, allows).length > 0 || (a === 'Work' && allows(cell('chat', 'run')) === true));
}

/** The page an area opens when the person has not been in it: its first row, or New chat for the chat-only. */
export function firstPageOf(area: AreaName, allows: Allows): string {
  const first = rowsOfArea(area, allows)[0];
  if (!first) return '/chat';
  return ownOffered(allows, first) ? first.url : (childrenOffered(allows, first)[0]?.url ?? first.url);
}

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
      for (const url of [item.url, ...(item.also ?? [])]) {
        if (covers(url, pathname) && (!best || url.length > best.len)) best = { group, item, len: url.length };
      }
      for (const child of item.children ?? []) {
        if (covers(child.url, pathname) && (!best || child.url.length > best.len)) best = { group, item, child, len: child.url.length };
      }
    }
  }
  return best && { group: best.group, item: best.item, child: best.child };
}

/** The area a path belongs to, from its longest matching entry; null for a page outside the sidebar (a hosted form). */
export function areaOf(pathname: string): AreaName | null {
  return navMatch(pathname)?.group.label ?? null;
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
  // Work's pages are the everyday ones, so their trail names no area.
  const group: Crumb[] = best.group === NAV[0] ? [] : [{ label: best.group.label }];
  // My connectors already names its view, so only the Data row's trail adds it (Team setup).
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
