'use client';

import { RouteTabs } from '@/components/shared/route-tabs';

/** Files' two pages: every file, and the folders whose files arrive by themselves. Everyone who reads Files sees both. */
export function FilesTabs() {
  return (
    <RouteTabs
      tabs={[
        { href: '/data/files', label: 'All files', testId: 'files-tab-all' },
        { href: '/data/files/watches', label: 'Watched folders', testId: 'files-tab-watches' },
      ]}
    />
  );
}
