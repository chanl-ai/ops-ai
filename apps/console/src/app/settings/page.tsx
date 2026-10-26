import { redirect } from 'next/navigation';

import { SETTINGS_NAV } from '@/lib/settings-tree';

/** Settings opens on the first page of its sidebar (Workspace › General); the sidebar lists every section. */
export default function SettingsRedirect() {
  redirect(SETTINGS_NAV[0].href);
}
