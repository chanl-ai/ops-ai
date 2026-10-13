import type { OpsApi } from './contract';
import { DEFAULT_USER_ID, DEMO_PASSWORD, DEMO_TOTP, USERS } from './mock/auth/seed';
import { createCasesOnlyHttp, createChatOnlyHttp, createHttpApi, createRegistryOnlyHttp, createToolsOnlyHttp } from './http';
import { createMockApi } from './mock';
import { createMockAuthProvider } from './mock/auth';
import type { AuthProvider } from '@/lib/auth/provider';
import { createFirebaseProvider } from '@/lib/auth/providers/firebase';
import { createOidcProvider } from '@/lib/auth/providers/oidc';
import { createPlatformProvider } from '@/lib/auth/providers/platform';
import { createPlatformTeamsHttp } from './platform-http';
import { setIdentitySource } from './request-identity';
import { clearChosenTeam } from './team-context';

const baseUrl = process.env.NEXT_PUBLIC_OPS_API_URL;
const chatUrl = process.env.NEXT_PUBLIC_OPS_CHAT_API_URL;
const casesUrl = process.env.NEXT_PUBLIC_OPS_CASES_API_URL;
const registryUrl = process.env.NEXT_PUBLIC_OPS_REGISTRY_API_URL;
const platformUrl = process.env.NEXT_PUBLIC_OPS_PLATFORM_API_URL;
const toolsUrl = process.env.NEXT_PUBLIC_OPS_TOOLS_API_URL;
const authProviderName = process.env.NEXT_PUBLIC_AUTH_PROVIDER ?? 'mock';

/**
 * Mock until a backend URL is configured; nothing outside this file knows which is in use.
 * NEXT_PUBLIC_OPS_API_URL: every area over HTTP. Each per-area URL points one area at the agents service and leaves
 * every other area as before, so the console can run against it before the rest of the backend exists:
 * NEXT_PUBLIC_OPS_CHAT_API_URL for chat, NEXT_PUBLIC_OPS_CASES_API_URL for the Cases runs and Reviews,
 * NEXT_PUBLIC_OPS_REGISTRY_API_URL for Agents and Workflows, NEXT_PUBLIC_OPS_TOOLS_API_URL for tool modules (tools-service).
 */
function createApi(): OpsApi {
  let api = baseUrl ? createHttpApi(baseUrl) : createMockApi();
  if (chatUrl) api = { ...api, chat: createChatOnlyHttp(chatUrl) };
  if (casesUrl) {
    const { runs, run, startRun, startable, reviews } = createCasesOnlyHttp(casesUrl);
    api = { ...api, cases: { ...api.cases, runs, run, startRun, startable }, reviews };
  }
  if (registryUrl) api = { ...api, ...createRegistryOnlyHttp(registryUrl) };
  if (toolsUrl) api = { ...api, ...createToolsOnlyHttp(toolsUrl) };
  // Signed in through platform-service, the team switcher lists the person's own teams from it.
  if (authProviderName === 'platform' && platformUrl) api = { ...api, teams: createPlatformTeamsHttp(platformUrl) };
  return api;
}
export const api: OpsApi = createApi();


/**
 * The default demo sign-in when the mock adapter is in use: the default account's email and password plus the
 * authenticator code, so a local session needs no typing. Real adapters get null; the values never leave the mock.
 */
export function demoAccount(): { name: string; email: string; password: string; code: string } | null {
  if (authProviderName !== 'mock') return null;
  const account = USERS.find((u) => u.id === DEFAULT_USER_ID);
  return account ? { name: account.name, email: account.email, password: DEMO_PASSWORD, code: DEMO_TOTP } : null;
}

function createAuthProvider(): AuthProvider {
  if (authProviderName === 'platform') {
    if (!platformUrl) throw new Error('NEXT_PUBLIC_AUTH_PROVIDER=platform needs NEXT_PUBLIC_OPS_PLATFORM_API_URL, the platform-service URL.');
    const platform = createPlatformProvider(platformUrl);
    // Every service call then carries the signed-in person's access token and one of their teams.
    setIdentitySource({ current: platform.identity, renew: platform.renew });
    // A team picked by the last person in this tab is not the next person's.
    platform.onSessionChange((s) => s === null && clearChosenTeam());
    return platform;
  }
  if (authProviderName === 'oidc') return createOidcProvider();
  if (authProviderName === 'firebase') return createFirebaseProvider();
  return createMockAuthProvider({ stepUpUrl: casesUrl ?? chatUrl });
}

/**
 * How people sign in: one adapter picked by NEXT_PUBLIC_AUTH_PROVIDER (mock, platform, oidc or firebase; mock by
 * default). Read here because this is the only file that reads env; the console reaches it through `@/lib/auth`.
 * platform signs in against platform-service (NEXT_PUBLIC_OPS_PLATFORM_API_URL) and is the only adapter whose calls
 * carry a bearer token. The mock adapter mints step-ups from the agents service when chat or cases point at it,
 * since that service verifies them.
 */
export const authProvider: AuthProvider = createAuthProvider();

export { ApiError, type Lookups, type OpsApi } from './contract';
export { currentTeamId, DEFAULT_TEAM_ID, setCurrentTeamId, teamStore } from './team-context';

/** A demo can show another organisation's name and mark without a code change: both come from the console's own
 * env (gitignored .env.local), never from the repo. Unset, the workspace's own name and the team icon are shown. */
export const brand = {
  name: process.env.NEXT_PUBLIC_BRAND_NAME || undefined,
  logo: process.env.NEXT_PUBLIC_BRAND_LOGO || undefined,
};
