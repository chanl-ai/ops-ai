'use client';

import * as React from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Plus, Rocket } from 'lucide-react';
import { toast } from 'sonner';

import { CreateDeploymentDialog } from '@/components/deployments/create-deployment-dialog';
import { DeploymentsTable } from '@/components/deployments/deployments-table';
import { PageLayout } from '@/components/page-layout';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useCreateDeployment, useDeployments, useWorkflows } from '@/hooks/queries';
import { useCreateParam } from '@/hooks/use-create-param';
import { useTabParam } from '@/hooks/use-tab-param';
import type { DeployChannel } from '@/lib/types/domain';

import { McpTab } from './_parts/mcp-tab';

const TABS = ['all', 'email', 'api', 'widget', 'mcp', 'chat'] as const;
type Tab = (typeof TABS)[number];
const TAB_LABEL: Record<Tab, string> = { all: 'All', email: 'Mailbox', api: 'API', widget: 'Widget', mcp: 'MCP', chat: 'Chat' };
// One row is enough: the counts come from the list's channel facet and its total.
const COUNTS = { page: 1, pageSize: 1 };

export default function DeploymentsPage() {
  const [createOpen, setCreateOpen, variant] = useCreateParam();
  const [tab, setTab] = useTabParam(TABS, 'all');
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [focusTools, setFocusTools] = React.useState(params.get('focus') === 'tools');
  const counts = useDeployments(COUNTS);
  const workflows = useWorkflows({ page: 1, pageSize: 100 });
  const create = useCreateDeployment();
  // `?create=1` opens the create dialog, so other pages (an empty Cases list) can link straight to it.
  React.useEffect(() => {
    if (new URLSearchParams(window.location.search).get('create') === '1') setCreateOpen(true);
  }, []);
  const countOf = (t: Tab) => (t === 'all' ? counts.data?.pagination.total : counts.data?.facets.channel?.[t]);
  // Choosing MCP in the wizard lands on the exposed-workflows table, because exposing a workflow is how an MCP deployment is created.
  // One URL write: closing the wizard and switching tabs separately both start from the same query string,
  // and the second would put `?create=1` back and reopen the wizard.
  const chooseMcp = () => {
    setFocusTools(true);
    router.replace(`${pathname}?tab=mcp`, { scroll: false });
  };

  return (
    <PageLayout
      switcher
      icon={Rocket}
      title="Deployments"
      description="Where each published workflow or agent is reachable: a mailbox, the API, the chat widget, staff assistants over MCP, or console chat"
      tabs={
        <Tabs
          value={tab}
          onValueChange={(t) => {
            setFocusTools(false);
            setTab(t as Tab);
          }}
        >
          <TabsList>
            {TABS.map((t) => (
              <TabsTrigger key={t} value={t} data-testid={`deployments-tab-${t}`}>
                {TAB_LABEL[t]}
                {countOf(t) !== undefined && <span className="ml-1 text-muted-foreground tabular-nums">{countOf(t)}</span>}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      }
      actions={
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="size-4" /> New deployment
        </Button>
      }
    >
      {tab === 'mcp' ? (
        <>
          <McpTab focusTools={focusTools} />
          {/* The wizard stays reachable on this tab; another channel's deployment lands on that channel's tab. */}
          <CreateDeploymentDialog
            open={createOpen}
            onOpenChange={setCreateOpen}
            workflows={workflows.data?.data ?? []}
            initialChannel={variant === 'email' ? 'email' : undefined}
            onChooseMcp={chooseMcp}
            isPending={create.isPending}
            onSubmit={async (input) => {
              const d = await create.mutateAsync(input);
              toast.success(`Deployed ${d.name} to ${d.environment}`, { description: `Serving ${d.workflowName} v${d.version}.` });
              setTab(d.channel);
            }}
          />
        </>
      ) : (
        <DeploymentsTable
          key={tab}
          channel={tab === 'all' ? undefined : (tab as DeployChannel)}
          createOpen={createOpen}
          onCreateOpenChange={setCreateOpen}
          createChannel={variant === 'email' ? 'email' : undefined}
          onChooseMcp={chooseMcp}
        />
      )}
    </PageLayout>
  );
}
