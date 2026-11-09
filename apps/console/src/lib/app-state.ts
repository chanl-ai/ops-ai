/**
 * An app's state as people see it: the one table every screen reads for an app card's `appState` (GET /v1/apps), its
 * words, whether the app is on for the team, and the one next action for whoever manages the team's apps and for
 * anyone else. tools-service decides the state and who acts next (`appGroup`); nothing on a screen works either out
 * again.
 */

export type AppStateId =
  | 'connected'
  | 'test_failed'
  | 'needs_sign_in'
  | 'auth_config_broken'
  | 'needs_auth_config'
  | 'off'
  | 'not_installed'
  | 'removed';

/** Who acts next, as tools-service answers it beside the state. */
export type AppGroupId = 'on' | 'needs_you' | 'needs_admin' | 'gone';

/**
 * What to do next: turn_on saves the team setting and never signs in; add_auth_config opens the new auth config;
 * fix_auth_config opens the app's auth configs; connect adds another account to a connected app.
 */
export type AppAction = 'none' | 'connect' | 'turn_on' | 'add_auth_config' | 'fix_auth_config' | 'sign_in' | 'reconnect' | 'delete' | 'ask_admin';

export type AppTone = 'success' | 'warning' | 'muted' | 'destructive';

export interface AppStateShown {
  /** The words for someone who manages the team's apps. */
  label: string;
  /** The words for anyone else, where the state is the team's to act on and theirs is only to ask. */
  memberLabel?: string;
  tone: AppTone;
  /** On for the team: Settings offers Turn off. */
  on: boolean;
  /** Someone who manages the team's apps. */
  admin: AppAction;
  /** Anyone else on the team. */
  member: AppAction;
}

export const APP_STATES: Record<AppStateId, AppStateShown> = {
  connected: { label: 'Connected', tone: 'success', on: true, admin: 'connect', member: 'none' },
  test_failed: { label: 'Signed in, test failed', tone: 'warning', on: true, admin: 'reconnect', member: 'none' },
  needs_sign_in: { label: 'Needs sign-in', tone: 'warning', on: true, admin: 'sign_in', member: 'sign_in' },
  auth_config_broken: { label: 'Auth config needs fixing', memberLabel: 'Not working for your team yet', tone: 'warning', on: true, admin: 'fix_auth_config', member: 'ask_admin' },
  needs_auth_config: { label: 'Needs an auth config', memberLabel: 'Not set up for your team yet', tone: 'warning', on: false, admin: 'add_auth_config', member: 'ask_admin' },
  off: { label: 'Available', memberLabel: 'Not set up for your team yet', tone: 'muted', on: false, admin: 'turn_on', member: 'ask_admin' },
  not_installed: { label: 'Not installed', tone: 'muted', on: false, admin: 'none', member: 'none' },
  removed: { label: 'No longer installed', tone: 'destructive', on: false, admin: 'delete', member: 'none' },
};

/**
 * A state's words and the caller's next action: `manages` is the card's mayManage. When the team acts next
 * (needs_admin), anyone who does not manage the team's apps asks someone who does.
 */
export function appStateFor(state: AppStateId, group: AppGroupId, manages: boolean): AppStateShown & { action: AppAction } {
  // A card read from a source that sends no state (a sample) offers nothing rather than throwing.
  const shown = APP_STATES[state] ?? { label: '', tone: 'muted', on: false, admin: 'none', member: 'none' };
  const action = manages ? shown.admin : group === 'needs_admin' ? 'ask_admin' : shown.member;
  return { ...shown, action };
}

/** A state's words for the caller: the member's words when they do not manage the team's apps and have their own. */
export const labelFor = (state: AppStateId, manages: boolean): string => {
  const shown = APP_STATES[state];
  if (!shown) return '';
  return manages ? shown.label : (shown.memberLabel ?? shown.label);
};

/** The sentence that says what to add before an app can sign in. */
export const addAuthConfigFirst = (name: string) => `Add an auth config for ${name} first.`;

/** What an app page's header offers: one button or link, or nothing. */
export type HeaderAction = 'turn_on' | 'add_auth_config' | 'fix_auth_config' | 'own_sign_in' | 'connect' | 'reconnect' | 'ask_admin' | null;

/**
 * The app page header's one control, from the card's state and who acts next, and nothing else: the caller's own
 * sign-in is made on Mine; a team account's, by someone who manages the team's apps, in the Connect window.
 */
export function headerActionFor(card: { appState: AppStateId; appGroup: AppGroupId; mayManage?: boolean | null }): HeaderAction {
  const { action } = appStateFor(card.appState, card.appGroup, Boolean(card.mayManage));
  switch (action) {
    case 'sign_in':
      return card.appGroup === 'needs_you' ? 'own_sign_in' : 'connect';
    case 'turn_on':
    case 'add_auth_config':
    case 'fix_auth_config':
    case 'connect':
    case 'reconnect':
    case 'ask_admin':
      return action;
    default:
      return null;
  }
}
