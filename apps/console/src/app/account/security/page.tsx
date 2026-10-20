import { redirect } from 'next/navigation';

/** Security moved with My account into the settings tree (c-178); this path stays for old links. */
export default function AccountSecurityRedirect() {
  redirect('/settings/account/security');
}
