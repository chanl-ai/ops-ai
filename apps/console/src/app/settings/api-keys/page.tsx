import { redirect } from 'next/navigation';

/** API keys moved in the settings tree (c-178); this path stays for old links. */
export default function ApiKeysRedirect() {
  redirect('/settings/team/api-keys');
}
