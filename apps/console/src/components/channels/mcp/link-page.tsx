'use client';

import { Pause, Play, Plug } from 'lucide-react';
import { toast } from 'sonner';

import { PageLayout } from '@/components/page-layout';
import { BuilderOnly } from '@/components/shared/builder-only';
import { QueryError } from '@/components/shared/query-states';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { LoadingButton } from '@/components/shared/loading-button';
import { Badge } from '@/components/ui/badge';
import { PageTabPanel, PageTabs } from '@/components/shared/page-tabs';
import { TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useMcpLink, usePauseMcpLink } from '@/hooks/mcp-link-queries';
import { useApiKeys } from '@/hooks/settings-queries';
import { useTeam } from '@/hooks/use-team';
import { useTabParam } from '@/hooks/use-tab-param';
import { plural } from '@/lib/format';

import { CallsTab } from './calls-tab';
import { ConnectTab } from './connect-tab';
import { KeysTab } from './keys-tab';
import { ToolsTab } from './tools-tab';

const TABS = ['connect', 'tools', 'keys', 'calls'] as const;

/** One MCP link: how to connect, the tools it offers, the team's keys that open it, and the calls made through it. */
export function McpLinkPage({ id }: { id: string }) {
  const q = useMcpLink(id);
  const pause = usePauseMcpLink(id);
  const { team } = useTeam();
  const keys = useApiKeys({ page: 1, pageSize: 100, filters: { mcpLink: [id] } });
  const [tab, setTab] = useTabParam(TABS, 'connect');
  if (q.isLoading) return <RecordSkeleton />;
  if (q.isError && !q.data)
    return (
      <PageLayout icon={Plug} title="MCP link" description="Channels › MCP" backHref="/build/channels/mcp">
        <QueryError what="the MCP link" onRetry={() => void q.refetch()} error={q.error} back={{ label: 'Back to MCP links', href: '/build/channels/mcp' }} />
      </PageLayout>
    );
  const link = q.data!;
  const toggle = () =>
    pause.mutate(!link.paused, {
      onSuccess: (l) => toast.success(l.paused ? `Paused ${l.name}` : `Resumed ${l.name}`, { description: l.paused ? 'Its address refuses every request until it is resumed.' : 'Assistants can connect again.' }),
      onError: (e) => toast.error('Couldn’t change the link', { description: e.message }),
    });
  const keyCount = keys.data?.data.filter((k) => !('status' in k) || (k as { status?: string }).status === 'active').length;
  return (
    <PageTabs value={tab} onValueChange={(v) => setTab(v as (typeof TABS)[number])}>
      <PageLayout
        icon={Plug}
        title={
          <span className="flex items-center gap-2">
            {link.name}
            <Badge variant="outline">Test</Badge>
            {link.paused && (
              <Badge variant="outline" className="border-warning/40 text-warning-text">
                Paused
              </Badge>
            )}
          </span>
        }
        description={`${team?.name ?? link.teamId} · ${plural(link.toolCount, 'tool')}`}
        backHref="/build/channels/mcp"
        actions={
          <BuilderOnly area="deployments">
            <LoadingButton variant="outline" isLoading={pause.isPending} onClick={toggle} data-testid="mcp-link-pause">
              {link.paused ? <Play className="size-4" /> : <Pause className="size-4" />} {link.paused ? 'Resume' : 'Pause'}
            </LoadingButton>
          </BuilderOnly>
        }
        tabs={
          <TabsList>
            <TabsTrigger value="connect">Connect</TabsTrigger>
            <TabsTrigger value="tools">Tools · {link.toolCount}</TabsTrigger>
            <TabsTrigger value="keys">Keys{keyCount !== undefined ? ` · ${keyCount}` : ''}</TabsTrigger>
            <TabsTrigger value="calls" data-testid="mcp-link-calls-tab">
              Calls
            </TabsTrigger>
          </TabsList>
        }
      >
        <div className="pb-16 pt-4" data-testid="mcp-link-page">
          <PageTabPanel value="connect">
            <ConnectTab link={link} />
          </PageTabPanel>
          <PageTabPanel value="tools">
            <ToolsTab link={link} />
          </PageTabPanel>
          <PageTabPanel value="keys">
            <KeysTab linkId={link.id} />
          </PageTabPanel>
          <PageTabPanel value="calls">
            <CallsTab linkId={link.id} />
          </PageTabPanel>
        </div>
      </PageLayout>
    </PageTabs>
  );
}
