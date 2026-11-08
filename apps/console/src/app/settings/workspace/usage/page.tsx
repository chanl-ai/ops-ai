'use client';

import * as React from 'react';
import { Activity, ChartColumn, Coins, Hash, Wrench } from 'lucide-react';

import { cad } from '@/components/logs/log-meta';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { UsageChart, UsageTable } from '@/components/settings/usage-panels';
import { EmptyState } from '@/components/shared/empty-state';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { NoAccess, QueryError } from '@/components/shared/query-states';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useNavAllows } from '@/hooks/me-queries';
import { useUsage } from '@/hooks/settings-queries';
import { count } from '@/lib/format';
import { USAGE } from '@/lib/settings-tree';
import type { UsageDays } from '@/lib/types/settings';

export default function UsagePage() {
  const [days, setDays] = React.useState<UsageDays>(30);
  const may = useNavAllows()(USAGE);
  const query = useUsage(days, may === true);
  const r = query.data;
  const all = r?.scope === 'all';
  const trend = r?.totals.costTrendPct ?? 0;

  return (
    <SettingsPageLayout
      section="Usage and cost"
      description={all ? 'Model cost, tokens and tool calls for every team, for internal chargeback.' : `Model cost, tokens and tool calls for ${r?.teamName ?? 'this team'}, for internal chargeback.`}
      actions={
        <ToggleGroup type="single" variant="outline" value={String(days)} onValueChange={(v) => v && setDays(Number(v) as UsageDays)} aria-label="Period">
          <ToggleGroupItem value="7" className="px-3">
            7 days
          </ToggleGroupItem>
          <ToggleGroupItem value="30" className="px-3">
            30 days
          </ToggleGroupItem>
        </ToggleGroup>
      }
    >
      {may === false ? (
        <NoAccess what="usage and cost" />
      ) : query.isPending ? (
        <PageSkeleton statCards={4} showToolbar={false} tableRows={6} />
      ) : query.isError && !r ? (
        <QueryError what="usage" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
      ) : r && r.byWorkflow.length === 0 ? (
        <EmptyState icon={ChartColumn} title="No usage in this period" description="Usage appears once a workflow in this team runs. Model cost and tool calls are counted per run." />
      ) : r ? (
        <div className="flex flex-col gap-4">
          <StatCardGrid columns={4}>
            <StatCard
              label={`Model cost · ${days} days`}
              value={cad(r.totals.modelCost)}
              icon={Coins}
              trend={trend ? { value: `${Math.abs(trend)}%`, direction: trend > 0 ? 'up' : 'down', isPositive: trend < 0 } : undefined}
              footer={{ text: `vs the ${days} days before`, subtext: 'Model use, in CAD' }}
            />
            <StatCard label="Tokens" value={count(r.totals.tokens)} icon={Hash} footer={{ text: 'Input and output', subtext: 'Across every model' }} />
            <StatCard label="Tool calls" value={count(r.totals.toolCalls)} icon={Wrench} footer={{ text: 'Made by agents and workflows', subtext: 'Reads and approved writes' }} />
            <StatCard label="Runs" value={count(r.totals.runs)} icon={Activity} footer={{ text: `${cad(r.totals.runs ? r.totals.modelCost / r.totals.runs : 0)} per run`, subtext: 'Model cost ÷ runs' }} />
          </StatCardGrid>

          <UsageChart report={r} />

          {all && <UsageTable title="By team" description="What each team is charged back for this period" rows={r.byTeam} />}
          <UsageTable title="By workflow" description={all ? 'Every workflow, with its team' : 'Each workflow in this team'} rows={r.byWorkflow} showTeam={all} />
          <p className="text-xs text-muted-foreground">Model cost is the model’s list price for the tokens each run used. Tool calls are counted, not priced.</p>
        </div>
      ) : null}
    </SettingsPageLayout>
  );
}
