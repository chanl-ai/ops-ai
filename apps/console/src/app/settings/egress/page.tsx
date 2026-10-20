import { redirect } from 'next/navigation';

/** Egress moved in the settings tree (c-178); this path stays for old links. */
export default function EgressRedirect() {
  redirect('/settings/security/egress');
}
