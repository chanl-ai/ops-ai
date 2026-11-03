'use client';

import { RouteTabs } from '@/components/shared/route-tabs';

/** A tool's page tabs: General (its call and Mock or Real) and Logs (its calls through the gateway). */
export function ToolTabs({ moduleId, operation }: { moduleId: string; operation: string }) {
  const base = `/tools/${encodeURIComponent(moduleId)}/operations/${encodeURIComponent(operation)}`;
  return (
    <RouteTabs
      tabs={[
        { href: base, label: 'General', testId: 'tool-tab-general' },
        { href: `${base}/logs`, label: 'Logs', testId: 'tool-tab-logs' },
      ]}
    />
  );
}
