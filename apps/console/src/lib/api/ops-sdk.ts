/**
 * The generated TypeScript SDK (@chanl-ai/ops-ai) as the console's screens call it (c-580). Its typed operations go out
 * through the console's own fetch (request-identity), so each call carries the signed-in person's token and team and
 * renews an expired token once, like every other console call. A refusal comes back as the console's ApiError, so
 * QueryError and the not-found and other-team states read it unchanged.
 *
 * New screens call services through `sdk()`; the area clients beside this file stay until their screens move. The SDK
 * comes through its workspace link as built output: its `prepare` script builds it on `pnpm install`.
 */
import { OpsAI, OpsError, type Service } from '@chanl-ai/ops-ai';

import { ApiError } from './contract';
import { serviceUrls } from './index';
import { fetchWithIdentity } from './request-identity';

/** Each service's origin; the SDK adds each operation's own `/v1/...` path. */
const origin = (url: string | undefined) => url?.replace(/\/+$/, '').replace(/\/v1$/, '') || undefined;
const SERVICES: Partial<Record<Service, string | undefined>> = Object.fromEntries(
  Object.entries(serviceUrls).map(([service, url]) => [service, origin(url)]),
);

/**
 * The SDK's request through request-identity. Its User-Agent header is dropped: a browser cannot set one, and as a
 * header outside the services' CORS list it would fail the preflight.
 */
const viaIdentity: typeof fetch = (input, init) => {
  const headers: Record<string, string> = {};
  new Headers(init?.headers).forEach((value, key) => {
    if (key !== 'user-agent') headers[key] = value;
  });
  return fetchWithIdentity(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, {
    ...init,
    headers,
  });
};

let client: OpsAI | undefined;

/** The one SDK client, made on first use; retries stay with the console's query layer, as for every other call. */
export function opsSdk(): OpsAI {
  client ??= new OpsAI({
    baseUrl: typeof window === 'undefined' ? 'http://localhost' : window.location.origin,
    services: Object.fromEntries(Object.entries(SERVICES).filter(([, url]) => url)) as Partial<Record<Service, string>>,
    fetch: viaIdentity,
    maxRetries: 0,
  });
  return client;
}

/** Runs SDK calls and turns the SDK's errors into the console's ApiError, with the API's code, message and details. */
export async function sdk<T>(call: (ops: OpsAI) => Promise<T>): Promise<T> {
  try {
    return await call(opsSdk());
  } catch (e) {
    if (e instanceof OpsError) {
      const details = e.details && typeof e.details === 'object' ? (e.details as Record<string, unknown>) : undefined;
      throw new ApiError(e.message.replace(/^\d+ [\w.]+: /, '').replace(/ \(request [^)]+\)$/, ''), e.status, undefined, e.code, details);
    }
    throw e;
  }
}
