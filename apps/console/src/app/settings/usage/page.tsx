import { redirect } from 'next/navigation';

/** Usage and cost moved in the settings tree (c-178); this path stays for old links. */
export default function UsageandcostRedirect() {
  redirect('/settings/workspace/usage');
}
