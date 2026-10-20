import { redirect } from 'next/navigation';

/** My account moved into the settings tree (c-178); this path stays for old links and the avatar menu. */
export default function AccountRedirect() {
  redirect('/settings/account');
}
