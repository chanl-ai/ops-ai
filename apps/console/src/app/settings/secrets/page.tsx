import { redirect } from 'next/navigation';

/** Secrets moved in the settings tree (c-178); this path stays for old links. */
export default function SecretsRedirect() {
  redirect('/settings/security/secrets');
}
