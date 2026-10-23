// `@/lib/api` inside the embed app (c-158): the console's hooks and components read `api` from here, so they talk to
// the widget API (`/v1/widget/{deployment}`) with the session the loader passed in, never to console routes. Only
// `api.chat` exists; calling any other area rejects, so a console hook that has no place in the embed fails loudly.
import type { ChatApi } from '@/lib/api/chat-contract';
import { ApiError, type OpsApi } from '@/lib/api/contract';
import { readSse } from '@/lib/api/sse';
import { AuthError, type AuthProvider } from '@/lib/auth/provider';

let deployment = '';
let session: string | null = null;
const ended = new Set<() => void>();

/** Which deployment this page serves; set once when the page loads. */
export function setDeployment(id: string) {
  deployment = id;
}

/** The session the loader handed over, or null when signed out. */
export function setSession(value: string | null) {
  session = value;
}

/** Called when the widget API answers 401: the session ended and the loader is asked for a fresh one. */
export function onSessionEnded(fn: () => void): () => void {
  ended.add(fn);
  return () => ended.delete(fn);
}

const base = () => `/v1/widget/${encodeURIComponent(deployment)}`;

async function call(method: string, path: string, body?: unknown, accept = 'application/json', signal?: AbortSignal): Promise<Response> {
  if (!session) throw new ApiError('Sign in to use the assistant.', 401, undefined, 'signed_out');
  const res = await fetch(`${base()}${path}`, {
    method,
    headers: { 'X-Widget-Session': session, 'Content-Type': 'application/json', Accept: accept },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (res.ok) return res;
  const err = await res.json().catch(() => null);
  if (res.status === 401) ended.forEach((fn) => fn());
  throw new ApiError(err?.error?.message ?? res.statusText, res.status, undefined, err?.error?.code, err?.error?.details);
}

async function json<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await call(method, path, body);
  return ((await res.json()) as { data: T }).data;
}

const refused = (what: string) => () => {
  throw new ApiError(`The embedded chat cannot ${what}.`, 501);
};

const chat: ChatApi = {
  agents: async () => [],
  settings: new Proxy({} as ChatApi['settings'], { get: () => refused('change thread settings') }),
  // The widget talks to one agent and keeps no memories of its own; both are console features.
  defaultAgent: new Proxy({} as ChatApi['defaultAgent'], { get: () => refused('change the default agent') }),
  memories: new Proxy({} as ChatApi['memories'], { get: () => refused('read memories') }),
  threads: {
    list: refused('list conversations') as never,
    get: (id) => json('GET', `/threads/${id}`),
    // The widget thread always runs the deployment's pinned agent; the input's agent and bases are the server's to set.
    create: () => json('POST', '/threads'),
    update: refused('rename conversations') as never,
    remove: refused('delete conversations') as never,
    bulkUpdate: refused('change conversations') as never,
    bulkRemove: refused('delete conversations') as never,
  },
  async *send(threadId, input, signal) {
    const res = await call('POST', `/threads/${threadId}/messages`, input, 'text/event-stream', signal);
    yield* readSse(res);
  },
  feedback: refused('send feedback') as never,
  // Approvals are decided in Human Tasks and form submit is not built, so no widget acts from the embed.
  widgetAction: refused('act on a widget') as never,
  budget: (threadId, answer) => json('POST', `/threads/${threadId}/budget`, answer),
};

/** An area the embed has no route for: reading it is fine (hooks set up their mutations at render), calling it fails. */
function absent(area: string): unknown {
  const fail = () => Promise.reject(new ApiError(`The embedded chat has no ${area} API.`, 501));
  return new Proxy(fail, { get: (_t, key) => (key === 'then' ? undefined : absent(`${area}.${String(key)}`)) });
}

export const api = new Proxy({ chat } as Partial<OpsApi>, {
  get(target, area: string) {
    return area in target ? target[area as keyof OpsApi] : absent(area);
  },
}) as OpsApi;

export { ApiError, type OpsApi } from '@/lib/api/contract';
// Values the console's shared hooks read from `@/lib/api`; the embed has no files service and no teams.
export const filesOnService = false;
/** Widget calls carry the widget session, not a team, so the console's team queries run without waiting for one. */
export const queriesNeedTeam = false;
/** The bank page brands the widget itself; the console's demo brand never applies here. */
export const brand: { name?: string; logo?: string } = {};

const noSignIn = () => Promise.reject(new AuthError('The embedded chat signs nobody in; the bank page owns the session.', 'not_configured'));
/**
 * The console's sign-in seam, as the embed has it: no console session, ever. The widget's visitor is the deployment's
 * session token (setSession), not a person signed in to the console, so shared hooks that ask see nobody.
 */
export const authProvider: AuthProvider = {
  name: 'platform',
  enrolsMfa: false,
  getSession: () => Promise.resolve(null),
  onSessionChange: () => () => undefined,
  signInWithPassword: noSignIn,
  signInWithGoogle: noSignIn,
  signInOptions: noSignIn,
  startSso: noSignIn,
  completeSso: noSignIn,
  sendReset: noSignIn,
  resetPassword: noSignIn,
  mfa: { setup: noSignIn, enrol: noSignIn, verify: noSignIn },
  reauthenticate: noSignIn,
  startSsoStepUp: noSignIn,
  completeSsoStepUp: noSignIn,
  takeStepUp: () => null,
  signOut: () => Promise.resolve(),
};
