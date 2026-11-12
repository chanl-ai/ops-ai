import { redirect } from 'next/navigation';

/** Gate policies moved under Policies in the settings tree; this path stays for old links. */
export default function GatePoliciesRedirect() {
  redirect('/settings/policies/gates');
}
