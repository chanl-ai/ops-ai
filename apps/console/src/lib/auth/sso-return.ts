export type SsoReturn = 'link_required' | 'refused' | 'code';

/** What the identity provider's return to /sso/callback says. `link_required` is the one refusal a person can act on:
 * the email already has an account, which they link from their own session or join by a new invite. */
export function ssoReturn(params: { get(name: string): string | null }): SsoReturn {
  const error = params.get('error');
  if (error === 'link_required') return 'link_required';
  return error ? 'refused' : 'code';
}
