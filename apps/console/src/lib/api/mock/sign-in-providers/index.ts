import type { DomainCheck, SignInProvider } from '@/lib/types/sign-in';

import { ApiError } from '../../contract';
import type { SignInProvidersApi } from '../../sign-in-providers-contract';

const DAY = 86_400_000;
const record = (domain: string) => ({ name: domain, value: `ops-ai-verify=${[...domain].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 11).toString(36)}` });
const check = (domain: string, verifiedAt: string | null): DomainCheck => ({ domain, verifiedAt, record: record(domain) });

const SEED: SignInProvider[] = [
  { id: 'password', kind: 'password', label: 'Password', enabled: true, domains: [], oidc: null, saml: null, jit: null, groups: null, verification: [] },
  {
    id: 'oidc-northfield',
    kind: 'oidc',
    label: 'Northfield SSO',
    enabled: true,
    domains: ['northfield.ca', 'northfieldbank.com'],
    oidc: { issuer: 'https://login.northfield.ca/oidc', clientId: 'ops-console', clientSecretRef: 'northfield-oidc', scopes: null },
    saml: null,
    jit: { team: 'team_ops', role: 'chat_user' },
    groups: null,
    verification: [check('northfield.ca', new Date(Date.now() - 140 * DAY).toISOString()), check('northfieldbank.com', null)],
  },
];

/** Sample providers for a console with no platform-service. Verifying a domain passes unless it is under `example.`,
 * so the refusal can be seen; nothing outlives a reload. */
export function createMockSignInProviders(): SignInProvidersApi {
  let rows = structuredClone(SEED);
  const owner = (domain: string) => rows.find((p) => p.domains.includes(domain));
  return {
    list: async () => structuredClone(rows),
    save: async (id, input) => {
      const clash = input.domains.find((d) => owner(d) && owner(d)!.id !== id);
      if (clash) throw new ApiError(`${clash} is on another of this workspace's providers; remove it there first.`, 409, undefined, 'domain_taken');
      const before = rows.find((p) => p.id === id);
      const kept = (d: string) => before?.verification.find((c) => c.domain === d)?.verifiedAt ?? null;
      const saved: SignInProvider = {
        id,
        kind: input.kind,
        label: input.label,
        enabled: input.enabled,
        domains: [...input.domains].sort(),
        oidc: input.oidc ?? null,
        saml: input.saml ?? null,
        jit: input.jit ?? null,
        groups: input.groups ?? null,
        verification: [...input.domains].sort().map((d) => check(d, kept(d))),
      };
      rows = before ? rows.map((p) => (p.id === id ? saved : p)) : [...rows, saved];
      return structuredClone(saved);
    },
    remove: async (id) => {
      rows = rows.filter((p) => p.id !== id);
    },
    verifyDomain: async (domain) => {
      const p = owner(domain);
      if (!p) throw new ApiError('No such sign-in domain.', 404);
      const c = p.verification.find((x) => x.domain === domain)!;
      if (/(^|\.)example\./.test(domain)) throw new ApiError(`No TXT record ${c.record.value} on ${domain} (found no TXT records). DNS can take up to an hour to update.`, 422, undefined, 'domain_unverified');
      c.verifiedAt ??= new Date().toISOString();
      return structuredClone(p);
    },
    secretNames: async () => ['northfield-oidc'],
    samlMetadataUrl: 'https://platform.northfield.example/v1/auth/saml/metadata',
  };
}
