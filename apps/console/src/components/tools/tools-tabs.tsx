'use client';

import { RouteTabs } from '@/components/shared/route-tabs';

/** The Tools page's tabs: every tool, then the same list filtered to app tools or to the team's own, and every call. */
export function ToolsTabs() {
  return (
    <RouteTabs
      tabs={[
        { href: '/data/tools', label: 'All tools', testId: 'tools-tab-all' },
        { href: '/data/tools?kind=app', label: 'App tools', testId: 'tools-tab-app' },
        { href: '/data/tools?kind=custom', label: 'Custom tools', testId: 'tools-tab-custom' },
        { href: '/govern/activity/tool-calls', label: 'Logs', testId: 'tools-tab-logs' },
      ]}
    />
  );
}
