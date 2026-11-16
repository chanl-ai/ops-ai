// What a use case run against a deployed host (OPS_USECASE_BASE_URL) may do. docs/usecases/lib/deployed_guard.py
// applies the same rules inside a Python script's own harness. Each function returns the reason for a refusal.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { UseCase } from './registry.ts';
import { USECASE_DIR } from './resolve.ts';

// A host whose name says production is refused even when a pattern on the list would match it.
const PRODUCTION = /(^|[-.])(prod|production|prd|live)([-.]|$)/i;

export const HOSTS_FILE = 'deploy/fly/usecase-hosts.txt';

export function hostPatterns(text: string): string[] {
  return text.split('\n').map((l) => l.trim()).filter((l) => l && !l.startsWith('#'));
}

/** `*` is one name label, so `*-web.fly.dev` never matches `x.evil.example-web.fly.dev`. */
function matches(pattern: string, host: string): boolean {
  const source = [...pattern.toLowerCase()].map((c) => (c === '*' ? '[a-z0-9-]+' : c.replace(/[.+?^${}()|[\]\\-]/g, '\\$&'))).join('');
  return new RegExp(`^${source}$`).test(host);
}

export function hostRefusal(baseUrl: string, patterns: string[]): string | undefined {
  let url: URL;
  try {
    url = new URL(baseUrl);
  } catch {
    return `${baseUrl} is not a URL`;
  }
  if (url.protocol !== 'https:' || !url.hostname) return `${baseUrl} is not an https origin`;
  if (url.username || url.password || url.port || url.pathname.replace(/\//g, '') || url.search || url.hash) return `${baseUrl} is more than an origin (user, port, path or query)`;
  const host = url.hostname.toLowerCase();
  if (PRODUCTION.test(host)) return `${host} looks like production`;
  if (!patterns.some((p) => matches(p, host))) return `${host} is not in ${HOSTS_FILE}`;
  return undefined;
}

/** The refusal for a run of `targets` on `layer` against `baseUrl`, or undefined when it may go ahead. */
export function deployedRefusal(root: string, baseUrl: string, targets: UseCase[], layer: string | undefined): string | undefined {
  let patterns: string[];
  try {
    patterns = hostPatterns(readFileSync(join(root, HOSTS_FILE), 'utf8'));
  } catch {
    return `no ${HOSTS_FILE}, so no host is allowed`;
  }
  const host = hostRefusal(baseUrl, patterns);
  if (host) return host;
  if (layer !== 'api') return 'a deployed host takes only the api layer; pass LAYER=api';
  if (!targets.length) return `no use case is marked safe for a deployed host (the Deployed column of ${USECASE_DIR}/README.md)`;
  const unsafe = targets.filter((uc) => !uc.deployed || !uc.layers.includes('api'));
  if (unsafe.length) return `${unsafe.map((u) => u.id).join(', ')} not marked safe for a deployed host (the Deployed column of ${USECASE_DIR}/README.md)`;
  return undefined;
}
