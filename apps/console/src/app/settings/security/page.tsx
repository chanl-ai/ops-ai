import { redirect } from 'next/navigation';

/** Security is Sign-in, Egress and Secrets in the settings tree; the section opens on Sign-in. */
export default function SecurityRedirect() {
  redirect('/settings/security/sign-in');
}
