import { AuthError, type AuthProvider } from '../provider';

/**
 * An adapter whose SDK is not wired yet. Every call fails with the env value to set, so choosing it by mistake
 * shows what is missing instead of a blank login.
 */
export function unconfigured(name: 'oidc' | 'firebase', envHint: string): AuthProvider {
  const fail = (): never => {
    throw new AuthError(`Sign-in through ${name} is not configured. Set ${envHint}, or set NEXT_PUBLIC_AUTH_PROVIDER=mock.`, 'not_configured');
  };
  return {
    name,
    enrolsMfa: false,
    getSession: async () => fail(),
    onSessionChange: () => () => undefined,
    signInWithPassword: async () => fail(),
    signInWithGoogle: async () => fail(),
    startSso: async () => fail(),
    completeSso: async () => fail(),
    sendReset: async () => fail(),
    resetPassword: async () => fail(),
    mfa: { setup: async () => fail(), enrol: async () => fail(), verify: async () => fail() },
    reauthenticate: async () => fail(),
    startSsoStepUp: async () => fail(),
    completeSsoStepUp: async () => fail(),
    takeStepUp: () => null,
    signOut: async () => fail(),
  };
}
