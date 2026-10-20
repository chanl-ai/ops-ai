import { redirect } from 'next/navigation';

/** Sign-in moved in the settings tree (c-178); this path stays for old links. */
export default function SigninRedirect() {
  redirect('/settings/security/sign-in');
}
