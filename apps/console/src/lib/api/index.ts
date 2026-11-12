import type { OpsApi } from './contract';
import { DEFAULT_USER_ID, DEMO_PASSWORD, DEMO_TOTP, USERS } from './mock/auth/seed';
import { createCasesOnlyHttp, createChatOnlyHttp, createHttpApi, createKnowledgeOnlyHttp, createRegistryOnlyHttp,
  createRegistryToolsDirectory, createRegistryToolsList, createToolsOnlyHttp } from './http';
import { createMockApi } from './mock';
import { createMockAuthProvider } from './mock/auth';
import { createNoNotifications } from './notifications-none';
import type { AuthProvider } from '@/lib/auth/provider';
import { createFirebaseProvider } from '@/lib/auth/providers/firebase';
import { createOidcProvider } from '@/lib/auth/providers/oidc';
import { createPlatformProvider } from '@/lib/auth/providers/platform';
import { createPlatformAccessHttp } from './platform-access-http';
import { createPlatformPoliciesHttp, createPlatformSignInProvidersHttp, createPlatformTeamsHttp, createPlatformWorkspaceTeamsHttp } from './platform-http';
import { createDocumentsHttp, createExtractionsHttp, createLayoutsHttp } from './documents-http';
import { createFilesServiceHttp } from './files-service-http';
import { createModelsHttp } from './models-http';
import { createStorageHttp } from './storage-http';
import { setIdentitySource } from './request-identity';
import { clearChosenTeam } from './team-context';

/** Demo sign-in is offered by development builds and by production builds made with NEXT_PUBLIC_OPS_DEMO_SIGNIN=1 (cloud boxes). */
export const demoSignInOffered = process.env.NODE_ENV !== 'production' || process.env.NEXT_PUBLIC_OPS_DEMO_SIGNIN === '1';
const baseUrl = process.env.NEXT_PUBLIC_OPS_API_URL;
const chatUrl = process.env.NEXT_PUBLIC_OPS_CHAT_API_URL;
const casesUrl = process.env.NEXT_PUBLIC_OPS_CASES_API_URL;
const registryUrl = process.env.NEXT_PUBLIC_OPS_REGISTRY_API_URL;
const platformUrl = process.env.NEXT_PUBLIC_OPS_PLATFORM_API_URL;
const toolsUrl = process.env.NEXT_PUBLIC_OPS_TOOLS_API_URL;
const knowledgeUrl = process.env.NEXT_PUBLIC_OPS_KNOWLEDGE_API_URL;
const filesUrl = process.env.NEXT_PUBLIC_OPS_FILES_API_URL;
const documentsUrl = process.env.NEXT_PUBLIC_OPS_DOCUMENTS_API_URL;
const modelsUrl = process.env.NEXT_PUBLIC_OPS_MODELS_API_URL;
const embedUrl = process.env.NEXT_PUBLIC_OPS_EMBED_URL;
const authProviderName = process.env.NEXT_PUBLIC_AUTH_PROVIDER ?? 'mock';
const onPlatform = authProviderName === 'platform' && Boolean(platformUrl);
const onRealService = Boolean(chatUrl || casesUrl || registryUrl || toolsUrl || knowledgeUrl || (authProviderName === 'platform' && platformUrl));

/**
 * Mock until a backend URL is configured; nothing outside this file knows which is in use.
 * NEXT_PUBLIC_OPS_API_URL: every area over HTTP. Each per-area URL points one area at the agents service and leaves
 * every other area as before, so the console can run against it before the rest of the backend exists:
 * NEXT_PUBLIC_OPS_CHAT_API_URL for chat, NEXT_PUBLIC_OPS_CASES_API_URL for the Cases runs and Reviews,
 * NEXT_PUBLIC_OPS_REGISTRY_API_URL for Agents and Workflows, NEXT_PUBLIC_OPS_TOOLS_API_URL for tool modules (tools-service),
 * NEXT_PUBLIC_OPS_KNOWLEDGE_API_URL for knowledge bases, sources and documents (kb-service),
 * NEXT_PUBLIC_OPS_FILES_API_URL for Files and storage settings (files-service),
 * NEXT_PUBLIC_OPS_DOCUMENTS_API_URL for document types (documents-service),
 * NEXT_PUBLIC_OPS_MODELS_API_URL for the account's model provider keys (models-service),
 * NEXT_PUBLIC_OPS_EMBED_URL for the embed app that serves the chat loader in snippets.
 */
function createApi(): OpsApi {
  let api = baseUrl ? createHttpApi(baseUrl) : createMockApi();
  if (chatUrl) api = { ...api, chat: createChatOnlyHttp(chatUrl) };
  if (casesUrl) {
    const { runs, run, runState, startRun, startable, reviews } = createCasesOnlyHttp(casesUrl);
    api = { ...api, cases: { ...api.cases, runs, run, runState, startRun, startable }, reviews };
  }
  // The tool list is the registry's directory; tool writes have no route there and stay on the mock (createRegistryToolsList).
  if (registryUrl) api = { ...api, ...createRegistryOnlyHttp(registryUrl), tools: { ...api.tools, list: createRegistryToolsList(registryUrl), ...createRegistryToolsDirectory(registryUrl) } };
  // The chat loader and the iframe it opens are served by the embed app.
  if (embedUrl) api = { ...api, widgetDeployments: { ...api.widgetDeployments, scriptUrl: () => `${embedUrl.replace(/\/$/, '')}/embed/v1.js` } };
  // A link form's page is the embed app's too.
  if (embedUrl) api = { ...api, forms: { ...api.forms, pageUrl: (form) => `${embedUrl.replace(/\/$/, '')}${form.url}` } };
  if (toolsUrl) {
    // Activity (the tool-call log) is the gateway's own executions log; the audit log stays where it was.
    const { toolCalls, ...tools } = createToolsOnlyHttp(toolsUrl);
    api = { ...api, ...tools, governance: { ...api.governance, toolCalls } };
  }
  if (knowledgeUrl) api = { ...api, ...createKnowledgeOnlyHttp(knowledgeUrl) };
  if (filesUrl) api = { ...api, files: { ...api.files, ...createFilesServiceHttp(filesUrl), storage: createStorageHttp(filesUrl) } };
  if (modelsUrl) api = { ...api, ...createModelsHttp(modelsUrl) };
  if (documentsUrl) api = { ...api, files: { ...api.files, documentTypes: createDocumentsHttp(documentsUrl), extractions: createExtractionsHttp(documentsUrl), layouts: createLayoutsHttp(documentsUrl) } };
  // No service owns notifications yet: once any area is on a real service, the mock feed is not shown beside it.
  if (!baseUrl && onRealService) api = { ...api, notifications: createNoNotifications() };
  // Signed in through platform-service, the team switcher lists the person's own teams from it.
  if (onPlatform) {
    api = { ...api, teams: createPlatformTeamsHttp(platformUrl!), workspacePolicies: createPlatformPoliciesHttp(platformUrl!), workspaceTeams: createPlatformWorkspaceTeamsHttp(platformUrl!), signInProviders: createPlatformSignInProvidersHttp(platformUrl!) };
    // Members, invitations and the audit log are platform-service's; accepting signs the person in there.
    const access = createPlatformAccessHttp(
      platformUrl!,
      (token, name, password) => {
        if (!authProvider.acceptInvite) throw new Error('This sign-in adapter cannot accept an invitation.');
        return authProvider.acceptInvite(token, name, password);
      },
      (email) => authProvider.signInOptions(email),
    );
    api = { ...api, settings: { ...api.settings, members: access.members }, invites: access.invites, governance: { ...api.governance, audit: access.audit } };
  }
  return api;
}
export const api: OpsApi = createApi();

/**
 * Each area's pages and the service URL that serves them, so the console can mark the pages still on sample data as
 * Preview while real services answer beside them. A page is Preview when its longest matching prefix names an area
 * whose URL is unset; a path matching no prefix (dev pages, auth) is never marked. Nothing is marked on the all-mock
 * stack, where every page is sample data and a badge on a few would say the rest are not, nor when every area is over
 * HTTP. A new page belongs in this table with the URL that serves it, or it reads as real.
 */
const AREAS: { prefix: string; served: boolean }[] = [
  { prefix: '/build/agents', served: Boolean(registryUrl) },
  { prefix: '/build/workflows', served: Boolean(registryUrl) },
  // A members-only hosted form reads agents-service's /v1/forms/{slug}/members.
  { prefix: '/forms', served: Boolean(registryUrl) },
  // The run list (moved from Cases) reads the runs service.
  { prefix: '/build/runs', served: Boolean(casesUrl) },
  // Cases are agents-service's /v1/cases.
  { prefix: '/work/cases', served: Boolean(registryUrl) },
  { prefix: '/build/channels', served: Boolean(registryUrl) },
  { prefix: '/build/skills', served: Boolean(registryUrl) },
  { prefix: '/build/guardrails', served: Boolean(registryUrl) },
  { prefix: '/build/widgets', served: Boolean(registryUrl) },
  // Activity is agents-service's one list (/v1/activity).
  { prefix: '/govern/activity', served: Boolean(registryUrl) },
  // Background processes are agents-service's /v1/background.
  { prefix: '/govern/activity/background', served: Boolean(registryUrl) },
  { prefix: '/data/tools', served: Boolean(toolsUrl) },
  { prefix: '/settings/egress', served: Boolean(toolsUrl) },
  { prefix: '/settings/security/egress', served: Boolean(toolsUrl) },
  { prefix: '/settings/secrets', served: Boolean(toolsUrl) },
  { prefix: '/data/secrets', served: Boolean(toolsUrl) },
  { prefix: '/data/knowledge', served: Boolean(knowledgeUrl) },
  // A source's page sits under Connections but its data and settings are kb-service's.
  { prefix: '/data/sources', served: Boolean(knowledgeUrl) },
  { prefix: '/chat', served: Boolean(chatUrl) },
  { prefix: '/work/tasks', served: Boolean(casesUrl) },
  // Gate policies are not part of the cases service's routes: they stay on the mock while the queue is real.
  { prefix: '/settings/policies/gates', served: false },
  { prefix: '/settings/storage', served: Boolean(filesUrl) },
  { prefix: '/settings/workspace/storage', served: Boolean(filesUrl) },
  { prefix: '/settings/workspace/storage', served: Boolean(filesUrl) },
  { prefix: '/settings/workspace/model-providers', served: Boolean(modelsUrl) },
  { prefix: '/data/files', served: Boolean(filesUrl) },
  { prefix: '/data/document-types', served: Boolean(documentsUrl) },
  { prefix: '/govern/access', served: onPlatform },
  // Tool access lists tools-service's grants.
  { prefix: '/govern/access/tool-access', served: Boolean(toolsUrl) },
  { prefix: '/govern/activity/audit', served: onPlatform },
  { prefix: '/settings/account/memory', served: Boolean(chatUrl) },
  // A person's own sign-ins, a connection's sign-in setting and the sign-in pages are tools-service's.
  { prefix: '/settings/account/connectors', served: Boolean(toolsUrl) },
  { prefix: '/connections', served: Boolean(toolsUrl) },
  { prefix: '/settings/members', served: onPlatform },
  { prefix: '/settings/policies', served: onPlatform },
  { prefix: '/govern/policies', served: onPlatform },
  { prefix: '/settings/security/sign-in', served: onPlatform },
  // The home page's counts are agents-service's /v1/overview; matched exactly, so it marks no other page.
  { prefix: '/', served: Boolean(registryUrl) },
  // No service owns these yet.
  { prefix: '/deployments', served: false },
  { prefix: '/govern/evals', served: false },
  { prefix: '/govern/models', served: false },
  { prefix: '/data/connectors', served: false },
  { prefix: '/sources', served: false },
  { prefix: '/connect', served: false },
  { prefix: '/data/wiki', served: false },
  { prefix: '/prompt-blocks', served: false },
  { prefix: '/account', served: false },
  { prefix: '/settings', served: false },
];
/** Workspace policies are platform-service's; without it the page draws sample ones and says so. */
export const policiesOnService = onPlatform || Boolean(baseUrl);
/** Sources and their settings are kb-service's once its URL (or the all-HTTP URL) is set; otherwise the mock's. */
export const knowledgeOnService = Boolean(knowledgeUrl || baseUrl);
/** Files on files-service, which does not set retention or export evidence yet; the Files page hides those actions. */
export const filesOnService = Boolean(filesUrl) && !baseUrl;
/** A signed form link opens on the embed app; without its origin Share as a form is members-only. */
export const publicFormPage = Boolean(embedUrl);
/** What's new and Coming next as the build read them (next.config.ts); lib/changelog.ts parses them. */
export const changelogSource = process.env.OPS_CHANGELOG ?? '[]';
export const roadmapSource = process.env.OPS_ROADMAP ?? '[]';
// The commit this console was built from and its release tag, if it has one (next.config.ts; lib/version.ts words them).
export const buildTag = process.env.NEXT_PUBLIC_OPS_VERSION;
export const buildCommit = process.env.NEXT_PUBLIC_OPS_COMMIT;
/** NEXT_PUBLIC_OPS_CACHE=off: the console saves nothing to the browser (lib/query-cache.ts). */
export const cacheSetting = process.env.NEXT_PUBLIC_OPS_CACHE;
/** Every console call is answered for a team, so its queries wait for one (hooks/team-query.ts); the embed has none. */
export const queriesNeedTeam = true;
/** Invitations on platform-service go to the team in the request header and take no team of their own. */
export const invitesToCurrentTeam = onPlatform;

export function isPreviewPath(pathname: string): boolean {
  if (baseUrl || !onRealService) return false;
  // The Connections catalog and each app's page read tools-service; a connection's older pages under it
  // stay sample data until they move.
  if (pathname === '/data/connectors' || pathname.startsWith('/data/connectors/')) return false;
  const under = (prefix: string) => (prefix === '/' ? pathname === '/' : pathname === prefix || pathname.startsWith(`${prefix}/`));
  const area = AREAS.filter((a) => under(a.prefix)).sort((x, y) => y.prefix.length - x.prefix.length)[0];
  return !!area && !area.served;
}


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

export { ApiError, type Lookups, type OpsApi, SOMEONE_ELSES } from './contract';
export { currentTeamId, DEFAULT_TEAM_ID, ownTeamId, setCurrentTeamId, teamStore } from './team-context';

/** A demo can show another organisation's name and mark without a code change: both come from the console's own
 * env (gitignored .env.local), never from the repo. Unset, the workspace's own name and the team icon are shown. */
export const brand = {
  name: process.env.NEXT_PUBLIC_BRAND_NAME || undefined,
  logo: process.env.NEXT_PUBLIC_BRAND_LOGO || undefined,
};

/** The Feedback button in development: `1` when `make up` found the ui-feedback collector running. */
export const uiFeedback = process.env.NEXT_PUBLIC_UI_FEEDBACK;
/** Each service's address as the console is told it, for the generated SDK client (lib/api/ops-sdk.ts). */
export const serviceUrls = {
  platform: platformUrl,
  agents: registryUrl,
  tools: toolsUrl,
  kb: knowledgeUrl,
  files: filesUrl,
  documents: documentsUrl,
} as const;

/**
 * The release switches a changelog entry may name (lib/changelog.ts): an entry for a feature behind one shows in What's
 * new only while it is on. Each is read by its full name, as Next inlines only a literal `process.env.NEXT_PUBLIC_*`
 * reference; scripts/changelog-check.mjs keeps the same names. Empty: a shipped feature has no switch.
 */
export const releaseSwitches: Readonly<Record<string, boolean>> = {};
