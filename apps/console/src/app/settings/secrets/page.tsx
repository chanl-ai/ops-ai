import { redirect } from 'next/navigation';

/** Secrets moved in the settings tree; this path stays for old links. */
export default function SecretsRedirect() {
  redirect('/integrations/credentials?tab=secrets');
}
