import { redirect } from 'next/navigation';

/** General moved to Team in the settings tree (c-178); this path stays for old links. */
export default function GeneralRedirect() {
  redirect('/settings/team');
}
