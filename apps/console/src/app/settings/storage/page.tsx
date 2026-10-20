import { redirect } from 'next/navigation';

/** Storage moved under Workspace in the settings tree (c-178); this path stays for old links. */
export default function StorageRedirect() {
  redirect('/settings/workspace/storage');
}
