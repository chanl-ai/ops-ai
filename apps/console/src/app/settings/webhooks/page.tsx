import { redirect } from 'next/navigation';

/** Webhooks moved in the settings tree (c-178); this path stays for old links. */
export default function WebhooksRedirect() {
  redirect('/settings/team/webhooks');
}
