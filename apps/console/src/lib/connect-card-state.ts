import type { AppStateId } from './app-state.ts';

/**
 * A chat Connect card's state: the refused call's own account, never its app's state on Mine, since a person signed
 * in to one account of an app still has to connect the one the call named. A scope request or a refusal is answered
 * only by connecting again, so an existing sign-in does not settle it. Its words come from the one table.
 */
export function connectCardState(call: { reason: string; linked: boolean; connectedNow: boolean }): Extract<AppStateId, 'connected' | 'needs_sign_in'> {
  if (call.connectedNow) return 'connected';
  return call.reason !== 'insufficient_scope' && call.reason !== 'refused' && call.linked ? 'connected' : 'needs_sign_in';
}
