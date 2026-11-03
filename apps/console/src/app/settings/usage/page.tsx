import { redirect } from 'next/navigation';

/** Usage and cost moved in the settings tree; this path stays for old links. */
export default function UsageandcostRedirect() {
  redirect('/settings/workspace/usage');
}
