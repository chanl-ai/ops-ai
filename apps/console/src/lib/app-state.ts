/**
 * An app's state as people see it: the one table every screen reads for an app card's `appState` (GET /v1/apps), its
 * words, whether the app is on for the team, and the one next action for whoever manages the team's apps and for
 * anyone else. tools-service decides the state; nothing on a screen works it out again.
 */

export type AppStateId = 'connected' | 'test_failed' | 'needs_sign_in' | 'needs_auth_config' | 'off' | 'not_installed' | 'removed';

/** What to do next: turn_on saves the team setting and never signs in; add_auth_config opens the new auth config. */
export type AppAction = 'none' | 'turn_on' | 'add_auth_config' | 'sign_in' | 'reconnect' | 'delete' | 'ask_admin';

export type AppTone = 'success' | 'warning' | 'muted' | 'destructive';

export interface AppStateShown {
  label: string;
  tone: AppTone;
  /** On for the team: Settings offers Turn off. */
  on: boolean;
  /** Someone who manages the team's apps. */
  admin: AppAction;
  /** Anyone else on the team. */
  member: AppAction;
}

export const APP_STATES: Record<AppStateId, AppStateShown> = {
  connected: { label: 'Connected', tone: 'success', on: true, admin: 'none', member: 'none' },
  test_failed: { label: 'Signed in, test failed', tone: 'warning', on: true, admin: 'reconnect', member: 'none' },
  needs_sign_in: { label: 'Needs sign-in', tone: 'warning', on: true, admin: 'sign_in', member: 'sign_in' },
  needs_auth_config: { label: 'Needs an auth config', tone: 'warning', on: false, admin: 'add_auth_config', member: 'ask_admin' },
  off: { label: 'Available', tone: 'muted', on: false, admin: 'turn_on', member: 'ask_admin' },
  not_installed: { label: 'Not installed', tone: 'muted', on: false, admin: 'none', member: 'none' },
  removed: { label: 'No longer installed', tone: 'destructive', on: false, admin: 'delete', member: 'none' },
};

/** A state's words and next action for the caller: `manages` is the card's mayManage. */
export function appStateFor(state: AppStateId, manages: boolean): AppStateShown & { action: AppAction } {
  // A card read from a source that sends no state (a sample) offers nothing rather than throwing.
  const shown = APP_STATES[state] ?? { label: '', tone: 'muted', on: false, admin: 'none', member: 'none' };
  return { ...shown, action: manages ? shown.admin : shown.member };
}

/** The sentence that says what to add before an app can sign in. */
export const addAuthConfigFirst = (name: string) => `Add an auth config for ${name} first.`;
