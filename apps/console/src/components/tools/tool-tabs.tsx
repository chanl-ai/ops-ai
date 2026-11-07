'use client';

import { RouteTabs } from '@/components/shared/route-tabs';
import { useNavAllows } from '@/hooks/me-queries';
import { TOOL_CALL_LOG } from '@/lib/nav';

/** A tool's page tabs: General (its call and Mock or Real) and, with the call log's cell, Logs (its calls). */
export function ToolTabs({ moduleId, operation }: { moduleId: string; operation: string }) {
  const base = `/tools/${encodeURIComponent(moduleId)}/operations/${encodeURIComponent(operation)}`;
  const logs = useNavAllows()(TOOL_CALL_LOG) === true;
  return (
    <RouteTabs
      tabs={[
        { href: base, label: 'General', testId: 'tool-tab-general' },
        ...(logs ? [{ href: `${base}/logs`, label: 'Logs', testId: 'tool-tab-logs' }] : []),
      ]}
    />
  );
}
