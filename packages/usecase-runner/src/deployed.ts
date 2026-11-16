// What a use case run against a deployed host (OPS_USECASE_BASE_URL) may do. docs/usecases/lib/deployed_guard.py
// applies the same rules inside a Python script's own harness. Each function returns the reason for a refusal.
import type { UseCase } from './registry.ts';
import { USECASE_DIR } from './resolve.ts';

// A host whose name says production is refused even when it is the allowed one.
const PRODUCTION = /(^|[-.])(prod|production|prd|live)([-.]|$)/i;

/** The one deployed host a run may sign in to or write on: its exact name, set by the staging workflow from its app variable. */
export const STAGING_HOST_VAR = 'OPS_USECASE_STAGING_HOST';
const HOST_NAME = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/;
const LOOPBACK = new Set(['localhost', '127.0.0.1', '[::1]']);

/**
 * The reason `baseUrl` may not be signed in to or written on, or undefined. Only the exact host in OPS_USECASE_STAGING_HOST
 * qualifies (no pattern, so nobody else's app of the same shape does); unset or not a host name refuses every host. A
 * loopback origin is this machine's own stack, which `allowLoopback` admits for the walks a local proof drives.
 */
export function hostRefusal(baseUrl: string, env: NodeJS.ProcessEnv, allowLoopback = false): string | undefined {
  let url: URL;
  try {
    url = new URL(baseUrl);
  } catch {
    return `${baseUrl} is not a URL`;
  }
  if (allowLoopback && LOOPBACK.has(url.hostname) && !url.username && !url.password) return undefined;
  if (url.protocol !== 'https:' || !url.hostname) return `${baseUrl} is not an https origin`;
  if (url.username || url.password || url.port || url.pathname.replace(/\//g, '') || url.search || url.hash) return `${baseUrl} is more than an origin (user, port, path or query)`;
  const host = url.hostname.toLowerCase();
  if (PRODUCTION.test(host)) return `${host} looks like production`;
  const allowed = (env[STAGING_HOST_VAR] ?? '').trim().toLowerCase();
  if (!HOST_NAME.test(allowed)) return `${STAGING_HOST_VAR} is not set to a host name, so no host is allowed`;
  if (host !== allowed) return `${host} is not the staging host (${STAGING_HOST_VAR})`;
  return undefined;
}

/** For a walk that signs in and writes to STG_ORIGIN: exits before any browser starts when the origin is refused. */
export function requireStagingOrigin(origin: string | undefined, env: NodeJS.ProcessEnv = process.env): string {
  const refusal = origin ? hostRefusal(origin, env, true) : 'STG_ORIGIN is not set';
  if (refusal) {
    console.error(`refused by the staging-host guard: ${refusal}`);
    process.exit(2);
  }
  return origin as string;
}

/** The refusal for a run of `targets` on `layer` against `baseUrl` (the staging host from `env`), or undefined when it may go ahead. */
export function deployedRefusal(baseUrl: string, env: NodeJS.ProcessEnv, targets: UseCase[], layer: string | undefined): string | undefined {
  const host = hostRefusal(baseUrl, env);
  if (host) return host;
  if (layer !== 'api') return 'a deployed host takes only the api layer; pass LAYER=api';
  if (!targets.length) return `no use case is marked safe for a deployed host (the Deployed column of ${USECASE_DIR}/README.md)`;
  const unsafe = targets.filter((uc) => !uc.deployed || !uc.layers.includes('api'));
  if (unsafe.length) return `${unsafe.map((u) => u.id).join(', ')} not marked safe for a deployed host (the Deployed column of ${USECASE_DIR}/README.md)`;
  return undefined;
}
