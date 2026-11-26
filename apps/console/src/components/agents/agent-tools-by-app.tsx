'use client';

import * as React from 'react';
import { ChevronDown, Wrench, X } from 'lucide-react';

import { AgentToolsPicker, AppStateChip, ConnectAppButton, NotAddedLine, toolsOnWords, usePickerOpen } from '@/components/agents/agent-tools-picker';
import { AppLogo } from '@/components/shared/app-logo';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { Row, Rows, Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Skeleton } from '@/components/ui/skeleton';
import { useAgentToolAppTools, useAgentToolApps } from '@/hooks/agent-tool-apps-queries';
import type { AgentToolApp } from '@/lib/types/agent-tool-apps';

type Change = { add?: string[]; remove?: string[] };

/** The tools the agent holds of one app, read when the row opens, each with Remove. */
function HeldTools({ agentId, app, onChange }: { agentId: string; app: AgentToolApp; onChange: (c: Change) => void }) {
  const tools = useAgentToolAppTools(agentId, app.id, { granted: true });
  const rows = (tools.data?.pages ?? []).flatMap((p) => p.data);
  if (tools.isPending) return <Skeleton className="m-3 h-10" />;
  if (tools.isError && !tools.data) return <div className="p-3"><QueryError what={`${app.name} tools`} error={tools.error} onRetry={() => void tools.refetch()} retrying={tools.isFetching} /></div>;
  return (
    <ul className="divide-y border-t bg-muted/20" data-testid={`agent-tools-app-${app.id}-tools`}>
      {rows.map((t) => (
        <li key={t.id} className="flex min-w-0 items-start gap-3 py-2 pr-2 pl-14">
          <div className="min-w-0 flex-1">
            <p className="break-words text-sm">{t.label}</p>
            {t.description && <p className="line-clamp-2 text-xs text-muted-foreground">{t.description}</p>}
          </div>
          {app.kind === 'other' && <Badge variant="outline" className="border-warning/40 text-warning-text">Not offered now</Badge>}
          {t.requiresApproval && <Badge variant="outline">Review: {t.approval ?? 'every call'}</Badge>}
          <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${t.label}`} onClick={() => onChange({ remove: [t.id] })}>
            <X className="size-4" />
          </Button>
        </li>
      ))}
      {tools.hasNextPage && (
        <li className="py-2 pl-14">
          <Button type="button" variant="ghost" size="sm" disabled={tools.isFetchingNextPage} onClick={() => void tools.fetchNextPage()}>
            {tools.isFetchingNextPage ? 'Loading…' : 'Show more tools'}
          </Button>
        </li>
      )}
    </ul>
  );
}

function AppRow({ agentId, app, onChange }: { agentId: string; app: AgentToolApp; onChange: (c: Change) => void }) {
  const [open, setOpen] = React.useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen} asChild>
      <li data-testid={`agent-tools-app-${app.id}`}>
        <div className="flex min-w-0 flex-wrap items-center gap-3 px-4 py-2.5">
          <AppLogo name={app.name} className="size-8" />
          <div className="min-w-40 flex-1">
            <p className="break-words text-sm font-medium">{app.name}</p>
            <p className="text-xs text-muted-foreground tabular-nums">{[app.signIn, toolsOnWords(app)].filter(Boolean).join(' · ')}</p>
            <NotAddedLine app={app} testId={`agent-tools-not-added-${app.id}`} />
          </div>
          <AppStateChip app={app} />
          {!app.connected && <ConnectAppButton agentId={agentId} app={app} testId={`connect-app-${app.id}`} />}
          <CollapsibleTrigger asChild>
            <Button type="button" variant="ghost" size="sm" aria-label={`${open ? 'Hide' : 'Show'} ${app.name} tools`}>
              {open ? 'Hide tools' : 'Show tools'} <ChevronDown className={`size-4 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />
            </Button>
          </CollapsibleTrigger>
        </div>
        <CollapsibleContent>{open && <HeldTools agentId={agentId} app={app} onChange={onChange} />}</CollapsibleContent>
      </li>
    </Collapsible>
  );
}

/**
 * The agent's tools grouped by app, as the server groups them (GET /v1/agents/{id}/tool-apps?granted=true): one row per
 * app with its sign-in and how many of its tools the agent holds, opening to those tools with Remove. Grants the registry
 * no longer offers (`stale`) are listed apart, since no app can name them.
 */
export function AgentToolsByApp({
  agentId,
  agentName,
  count,
  stale,
  onChange,
  children,
}: {
  agentId: string;
  agentName: string;
  count: number;
  stale: string[];
  onChange: (c: Change) => void;
  children?: React.ReactNode;
}) {
  const apps = useAgentToolApps(agentId, { granted: true, limit: 50 });
  // Add tools waits for the section's own read, so the picker's first read is the only one in flight when it opens.
  const [pickerOpen, setPickerOpen] = usePickerOpen(agentId);
  const rows = (apps.data?.pages ?? []).flatMap((p) => p.data);
  return (
    <Section
      id="agent-tools"
      flush
      title={
        <span className="flex items-center gap-2">
          <Wrench className="size-4 text-muted-foreground" aria-hidden />
          Tools
          <span className="font-normal text-muted-foreground tabular-nums" data-testid="agent-tools-count">
            {count}
          </span>
        </span>
      }
      description="The only systems this agent may call. Tools marked review pause every call for a person."
      actions={<AgentToolsPicker hidden={apps.isPending} agentId={agentId} agentName={agentName} open={pickerOpen} onOpenChange={setPickerOpen} onGrant={(ids) => onChange({ add: ids })} />}
    >
      {apps.isPending ? (
        <Skeleton className="m-4 h-16" data-testid="agent-tools-loading" />
      ) : apps.isError && !apps.data ? (
        <div className="p-4">
          <QueryError what="this agent’s tools" error={apps.error} onRetry={() => void apps.refetch()} retrying={apps.isFetching} />
        </div>
      ) : rows.length || stale.length ? (
        <Rows testId="agent-tools-rows">
          {rows.map((a) => (
            <AppRow key={a.id} agentId={agentId} app={a} onChange={onChange} />
          ))}
          {stale.map((id) => (
            <Row
              key={id}
              wrap
              title={<code className="font-mono text-sm">{id}</code>}
              description="No longer offered: unpublished, hidden or removed from its module."
              trailing={
                <>
                  <Badge variant="outline" className="border-warning/40 text-warning-text">
                    Gone
                  </Badge>
                  <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${id}`} onClick={() => onChange({ remove: [id] })}>
                    <X className="size-4" />
                  </Button>
                </>
              }
            />
          ))}
        </Rows>
      ) : (
        <EmptyState
          icon={Wrench}
          title="No tools yet"
          description="The agent can only answer from knowledge. Add an app to let it look things up or act."
          action={{ label: 'Browse apps', onClick: () => setPickerOpen(true) }}
          testId="agent-tools-empty"
        />
      )}
      {apps.hasNextPage && (
        <div className="border-t p-2 text-center">
          <Button type="button" variant="ghost" size="sm" disabled={apps.isFetchingNextPage} onClick={() => void apps.fetchNextPage()}>
            {apps.isFetchingNextPage ? 'Loading…' : 'Show more apps'}
          </Button>
        </div>
      )}
      {children}
    </Section>
  );
}
