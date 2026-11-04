import { redirect } from 'next/navigation';

/** Egress moved in the settings tree; this path stays for old links. */
export default function EgressRedirect() {
  redirect('/settings/security/egress');
}
