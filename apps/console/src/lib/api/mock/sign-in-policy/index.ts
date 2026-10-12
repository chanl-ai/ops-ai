import type { SignInPolicy, SsoDomain } from '@/lib/types/sign-in';

import { ApiError } from '../../contract';
import type { SignInPolicyApi } from '../../sign-in-contract';
import { auditSink } from '../governance';
import { mode, respond } from '../runtime';

const DAY = 86_400_000;
const txtFor = (domain: string) => `ops-ai-verify=${[...domain].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7).toString(36)}`;
const DOMAIN_RE = /^(?=.{3,253}$)([a-z0-9-]+\.)+[a-z]{2,}$/;

/** Seed: SSO through Entra ID for northfield.ca, MFA required, invites only. The login screen reads this. */
export const SEED_POLICY: SignInPolicy = {
  methods: { password: true, sso: true, google: false },
  sso: {
    provider: 'entra',
    metadataUrl: 'https://login.microsoftonline.com/northfield.onmicrosoft.com/federationmetadata/2007-06/federationmetadata.xml',
    domains: [{ domain: 'northfield.ca', verified: true, txtRecord: txtFor('northfield.ca'), verifiedAt: new Date(Date.now() - 140 * DAY).toISOString() }],
    lastTest: { ok: true, at: new Date(Date.now() - 6 * DAY).toISOString(), message: 'Metadata fetched; test sign-in returned a signed assertion for northfield.ca' },
  },
  mfaRequired: true,
  sessionHours: 10,
  allowedDomains: ['northfieldbank.com', 'northfield.ca'],
  selfSignup: false,
  updatedAt: new Date(Date.now() - 6 * DAY).toISOString(),
  updatedBy: 'Priya Shah',
};

// Module-level so slices created without deps (Settings → Members inside governance) read the same live policy.
let live: SignInPolicy = structuredClone(SEED_POLICY);
/** The workspace sign-in policy as it stands now. */
export const currentSignInPolicy = (): SignInPolicy => live;

/** The sign-in policy store. `isSsoEmail` lets the invites slice decide SSO vs password for an invited address. */
export function createSignInPolicyMock(deps: { me: string }) {
  const policy: SignInPolicy = (live = structuredClone(SEED_POLICY));
  const snapshot = () => structuredClone(policy);
  const touch = (summary: string, diff: { field: string; before?: string; after?: string }[] = []) => {
    policy.updatedAt = new Date().toISOString();
    policy.updatedBy = deps.me;
    auditSink.log({ action: 'edited', target: { type: 'sign_in_policy', name: 'Sign-in policy', href: '/settings/sign-in' }, summary, diff });
  };
  const verified = () => policy.sso.domains.filter((d) => d.verified);
  const domainOf = (domain: string): SsoDomain => policy.sso.domains.find((d) => d.domain === domain) ?? (() => {
    throw new ApiError(`${domain} is not on the list.`, 404);
  })();
  const onOff = (v: boolean) => (v ? 'On' : 'Off');

  const api: SignInPolicyApi = {
    get: () => respond((m) => (m === 'empty' ? { ...snapshot(), sso: { ...snapshot().sso, domains: [], lastTest: undefined } } : snapshot())),
    save: (patch) =>
      respond(() => {
        const before = snapshot();
        if (patch.section === 'methods') {
          const m = patch.methods;
          if (!m.password && !m.sso && !m.google) throw new ApiError('Leave at least one way to sign in on.', 400);
          if (m.sso && !verified().length) throw new ApiError('Verify a domain in SSO connection before turning SSO on.', 400);
          policy.methods = { ...m };
          touch('Changed sign-in methods', (['password', 'sso', 'google'] as const).filter((k) => before.methods[k] !== m[k]).map((k) => ({ field: k === 'sso' ? 'SSO' : k === 'google' ? 'Google' : 'Password', before: onOff(before.methods[k]), after: onOff(m[k]) })));
        } else if (patch.section === 'sso') {
          if (!patch.metadataUrl.trim() && !patch.metadataFileId) throw new ApiError('Give the metadata URL or upload the metadata file.', 400);
          if (patch.metadataUrl.trim() && !/^https:\/\//.test(patch.metadataUrl.trim())) throw new ApiError('The metadata URL must start with https://.', 400);
          Object.assign(policy.sso, { provider: patch.provider, metadataUrl: patch.metadataUrl.trim(), metadataFileId: patch.metadataFileId, metadataFileName: patch.metadataFileName, lastTest: undefined });
          touch('Changed the SSO connection', [{ field: 'Identity provider', before: before.sso.provider, after: patch.provider }]);
        } else if (patch.section === 'security') {
          if (patch.sessionHours < 1 || patch.sessionHours > 24 * 7) throw new ApiError('Session length must be between 1 hour and 7 days.', 400);
          const bad = patch.allowedDomains.find((d) => !DOMAIN_RE.test(d));
          if (bad) throw new ApiError(`${bad} is not a domain.`, 400);
          Object.assign(policy, { mfaRequired: patch.mfaRequired, sessionHours: patch.sessionHours, allowedDomains: [...patch.allowedDomains] });
          touch('Changed sign-in security', [
            ...(before.mfaRequired !== patch.mfaRequired ? [{ field: 'MFA required', before: onOff(before.mfaRequired), after: onOff(patch.mfaRequired) }] : []),
            ...(before.sessionHours !== patch.sessionHours ? [{ field: 'Session length', before: `${before.sessionHours} h`, after: `${patch.sessionHours} h` }] : []),
            ...(before.allowedDomains.join() !== patch.allowedDomains.join() ? [{ field: 'Allowed domains', before: before.allowedDomains.join(', '), after: patch.allowedDomains.join(', ') }] : []),
          ]);
        } else {
          policy.selfSignup = patch.selfSignup;
          touch(patch.selfSignup ? 'Turned self-signup on' : 'Turned self-signup off', [{ field: 'Self-signup', before: onOff(before.selfSignup), after: onOff(patch.selfSignup) }]);
        }
        return snapshot();
      }),
    addDomain: (raw) =>
      respond(() => {
        const domain = raw.trim().toLowerCase();
        if (!DOMAIN_RE.test(domain)) throw new ApiError(`${raw} is not a domain, e.g. northfield.ca.`, 400);
        if (policy.sso.domains.some((d) => d.domain === domain)) throw new ApiError(`${domain} is already listed.`, 409);
        policy.sso.domains.push({ domain, verified: false, txtRecord: txtFor(domain) });
        touch(`Added SSO domain ${domain}`, [{ field: 'Domains', after: domain }]);
        return snapshot();
      }),
    verifyDomain: (domain) =>
      respond(() => {
        const d = domainOf(domain);
        if (d.verified) return snapshot();
        // The mock's DNS answers for any domain except ones under example., so the failure state can be seen.
        if (/\.example\.|^example\./.test(d.domain)) throw new ApiError(`No TXT record ${d.txtRecord} found on ${d.domain}. DNS can take up to an hour to update.`, 422);
        Object.assign(d, { verified: true, verifiedAt: new Date().toISOString() });
        touch(`Verified SSO domain ${d.domain}`, [{ field: d.domain, before: 'Unverified', after: 'Verified' }]);
        return snapshot();
      }),
    removeDomain: (domain) =>
      respond(() => {
        const d = domainOf(domain);
        if (d.verified && policy.methods.sso && verified().length === 1) throw new ApiError(`${domain} is the only verified domain and SSO is on. Turn SSO off first.`, 409);
        policy.sso.domains = policy.sso.domains.filter((x) => x !== d);
        touch(`Removed SSO domain ${domain}`, [{ field: 'Domains', before: domain }]);
        return snapshot();
      }),
    testConnection: () =>
      respond(() => {
        const m = mode();
        const ok = m !== 'error' && (!!policy.sso.metadataUrl || !!policy.sso.metadataFileId);
        const result = { ok, at: new Date().toISOString(), message: ok ? `Metadata fetched; test sign-in returned a signed assertion${verified()[0] ? ` for ${verified()[0].domain}` : ''}` : 'Could not fetch the metadata. Check the URL or upload the file.' };
        policy.sso.lastTest = result;
        auditSink.log({ action: 'edited', target: { type: 'sign_in_policy', name: 'Sign-in policy', href: '/settings/sign-in' }, summary: `Tested the SSO connection: ${ok ? 'passed' : 'failed'}` });
        return result;
      }),
  };

  /** True when the address belongs to a verified SSO domain and SSO is on. */
  const isSsoEmail = (email: string) => policy.methods.sso && verified().some((d) => email.toLowerCase().endsWith(`@${d.domain}`));
  return { api, isSsoEmail, policy: () => policy };
}
