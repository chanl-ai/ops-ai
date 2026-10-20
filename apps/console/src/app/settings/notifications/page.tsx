import { redirect } from 'next/navigation';

/** Notifications moved under Team in the settings tree (c-178); this path stays for old links and the header bell. */
export default function NotificationsRedirect() {
  redirect('/settings/team/notifications');
}
