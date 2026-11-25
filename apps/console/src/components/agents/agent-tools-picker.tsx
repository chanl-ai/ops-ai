'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowLeft, Check, Plus, Search } from 'lucide-react';

import { AppCard } from '@/components/connections/app-card';
import { AppStateBadge } from '@/components/connections/app-state-badge';
import { AskAnAdmin } from '@/components/connections/ask-an-admin';
import { ConnectSystemDialog, type ConnectTarget } from '@/components/connections/connect-system-dialog';
import { AppLogo } from '@/components/shared/app-logo';
import { DialogShell } from '@/components/shared/dialog-shell';
import { QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { useAgentToolAppTools, useAgentToolApps, useRefreshAgentToolApps } from '@/hooks/agent-tool-apps-queries';
import { useCan } from '@/hooks/me-queries';
import { useSystemCard, type AppState } from '@/hooks/systems-queries';
import { appPageHref } from '@/lib/app-links';
import { plural } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { AgentToolApp, AppTool } from '@/lib/types/agent-tool-apps';

/** How many of an app's tools the agent holds, in the words every app row and card use. */
export const toolsOnWords = (a: Pick<AgentToolApp, 'toolsGranted' | 'toolsOffered'>) => `${a.toolsGranted} of ${plural(a.toolsOffered, 'tool')}`;

/** How many of an app's tools the team has not turned on, with the way to turn them on: the app's Tools tab. */
export function NotAddedLine({ app, testId }: { app: Pick<AgentToolApp, 'id' | 'name' | 'notAdded'>; testId?: string }) {
  if (app.notAdded <= 0) return null;
  return (
    <p className="text-xs text-muted-foreground" data-testid={testId ?? 'tools-not-added'}>
      {`${plural(app.notAdded, 'more tool')} not turned on. `}
      <Link href={appPageHref(app.id, 'tools')} className="underline underline-offset-2 hover:text-foreground">
        {`Turn on from ${app.name}’s Tools tab`}
      </Link>
    </p>
  );
}

/** The app's state from its card (`appState`, the one owner of the words); a group with no card has none to show. */
export function AppStateChip({ app }: { app: Pick<AgentToolApp, 'appState' | 'connected'> }) {
  const manages = useCan('connections', 'manage') === true;
  if (!app.appState) return app.connected ? null : <Badge variant="outline">Not connected</Badge>;
  return <AppStateBadge card={{ appState: app.appState as AppState }} manages={manages} />;
}

const CardsSkeleton = () => (
  <div className="grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3" data-testid="tools-picker-loading">
    {[0, 1, 2, 3, 4, 5].map((i) => (
      <Skeleton key={i} className="h-24 w-full" />
    ))}
  </div>
);

/** One app as the Apps page draws it; a search that matched its tools lists them under the card, each added by a click. */
function AppTile({ app, onOpen, onAddTool }: { app: AgentToolApp; onOpen: () => void; onAddTool: (id: string) => void }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <AppCard
        testId={`tools-card-${app.id}`}
        linkTestId={`tools-app-${app.id}`}
        state={app.appState ?? undefined}
        name={app.name}
        subtitle={app.signIn}
        onOpen={onOpen}
        footState={<AppStateChip app={app} />}
      >
        <p className="text-xs text-muted-foreground tabular-nums">{app.toolsGranted > 0 ? `${toolsOnWords(app)} on` : plural(app.toolsOffered, 'tool')}</p>
      </AppCard>
      {app.matches.length > 0 && (
        <ul className="flex flex-col rounded-lg border bg-card py-1" aria-label={`Matching ${app.name} tools`}>
          {app.matches.map((m) => (
            <li key={m.id}>
              <button
                type="button"
                disabled={m.granted}
                onClick={() => onAddTool(m.id)}
                data-testid={`tools-match-${m.id}`}
                className="flex w-full min-w-0 items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent/50 disabled:cursor-default disabled:opacity-70 disabled:hover:bg-transparent"
              >
                {m.granted ? <Check className="size-3.5 shrink-0 text-success-text" aria-hidden /> : <Plus className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />}
                <span className="min-w-0 flex-1 truncate">{m.label}</span>
                <span className="shrink-0 text-xs capitalize text-muted-foreground">{m.granted ? 'Added' : m.access}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AppsStep({ agentId, search, onOpen, onAddTool }: { agentId: string; search: string; onOpen: (a: AgentToolApp) => void; onAddTool: (id: string) => void }) {
  const apps = useAgentToolApps(agentId, { search });
  const rows = (apps.data?.pages ?? []).flatMap((p) => p.data);
  if (apps.isPending) return <CardsSkeleton />;
  if (apps.isError && !apps.data) return <QueryError what="the apps" error={apps.error} onRetry={() => void apps.refetch()} retrying={apps.isFetching} testId="tools-picker-error" />;
  if (!rows.length)
    return (
      <div className="flex flex-col items-center gap-2 py-10 text-center" data-testid="tools-picker-empty">
        <Search className="size-5 text-muted-foreground" aria-hidden />
        <p className="text-sm font-medium">{search.trim() ? `No app or tool matches “${search.trim()}”` : 'No apps to add tools from'}</p>
        <p className="text-xs text-muted-foreground">Apps the team connects, and tools it adds from them, show here.</p>
        <MissingApp />
      </div>
    );
  // The server lists connected apps first; the heading goes where the order changes.
  const split = rows.findIndex((a) => !a.connected);
  const groups: [string, AgentToolApp[]][] = split === -1 ? [['Connected', rows]] : split === 0 ? [['Not connected', rows]] : [['Connected', rows.slice(0, split)], ['Not connected', rows.slice(split)]];
  return (
    <div className="flex flex-col gap-4" data-testid="tools-picker-apps">
      {groups.map(([heading, list]) => (
        <section key={heading} className="flex flex-col gap-2">
          <h3 className="text-xs font-medium text-muted-foreground">{heading}</h3>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3">
            {list.map((a) => (
              <AppTile key={a.id} app={a} onOpen={() => onOpen(a)} onAddTool={onAddTool} />
            ))}
          </div>
        </section>
      ))}
      {apps.hasNextPage && (
        <Button type="button" variant="outline" size="sm" className="self-center" disabled={apps.isFetchingNextPage} onClick={() => void apps.fetchNextPage()}>
          {apps.isFetchingNextPage ? 'Loading…' : 'Show more apps'}
        </Button>
      )}
    </div>
  );
}

/** Where an app that is not listed comes from: whoever manages the team's apps. */
function MissingApp() {
  return <AskAnAdmin testId="tools-picker-ask-admin" lead="An app missing?" />;
}

/**
 * Connect an app that is not connected: the app's own connect dialog for a person who manages the team's apps, Ask an
 * admin for anyone else. Pseudo-apps (Workflows, Agents) are always connected and never reach it.
 */
export function ConnectAppButton({ agentId, app, onConnected, testId }: { agentId: string; app: AgentToolApp; onConnected?: () => void; testId?: string }) {
  const [connecting, setConnecting] = React.useState(false);
  const card = useSystemCard(app.id);
  const refresh = useRefreshAgentToolApps(agentId);
  const target: ConnectTarget | null = card.data ? (card.data.kind === 'plugin' && card.data.plugin ? { kind: 'plugin', card: card.data } : { kind: 'module', moduleId: card.data.moduleIds[0] ?? '', name: card.data.name }) : null;
  if (card.isPending) return <Skeleton className="h-8 w-28" />;
  if (!card.data?.mayManage || !target) return <AskAnAdmin testId={testId ? `${testId}-ask-admin` : 'tools-app-ask-admin'} />;
  return (
    <>
      <Button type="button" size="sm" onClick={() => setConnecting(true)} data-testid={testId ?? 'tools-app-connect'}>
        Connect {app.name}
      </Button>
      {connecting && (
        <ConnectSystemDialog
          target={target}
          mode="connect"
          open
          onOpenChange={(o) => !o && setConnecting(false)}
          onConnected={() => {
            onConnected?.();
            void refresh();
          }}
        />
      )}
    </>
  );
}

function ConnectStrip({ agentId, app, onConnected }: { agentId: string; app: AgentToolApp; onConnected: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-card px-3 py-2.5" data-testid="tools-app-connection">
      <AppLogo name={app.name} className="size-8" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{app.name}</p>
        <p className="text-xs text-muted-foreground">{app.connected ? (app.signIn ?? 'Connected') : 'Needs a connection before the agent can call it'}</p>
      </div>
      {!app.connected && <ConnectAppButton agentId={agentId} app={app} onConnected={onConnected} />}
    </div>
  );
}

type ToolsQuery = ReturnType<typeof useAgentToolAppTools>;

function ToolRow({ tool, picked, onToggle }: { tool: AppTool; picked: boolean; onToggle: () => void }) {
  const id = `pick-${tool.id}`;
  return (
    <li className="flex items-start gap-3 px-3 py-2.5">
      <Checkbox id={id} data-testid={`tools-app-tool-${tool.id}`} className="mt-0.5" checked={tool.granted || picked} disabled={tool.granted} onCheckedChange={onToggle} />
      <Label htmlFor={id} className="min-w-0 flex-1 flex-col items-start gap-0.5 font-normal">
        <span className="break-words text-sm font-medium">{tool.label}</span>
        {tool.description && <span className="line-clamp-2 text-xs text-muted-foreground">{tool.description}</span>}
      </Label>
      <span className="flex shrink-0 flex-wrap items-center justify-end gap-1.5 text-xs text-muted-foreground">
        {tool.granted && <span>Added</span>}
        <span className="capitalize">{tool.access}</span>
        {tool.requiresApproval && <Badge variant="outline">Review: {tool.approval ?? 'every call'}</Badge>}
      </span>
    </li>
  );
}

function ToolsStep({ app, search, tools, picked, setPicked }: { app: AgentToolApp; search: string; tools: ToolsQuery; picked: Set<string>; setPicked: (s: Set<string>) => void }) {
  const rows = (tools.data?.pages ?? []).flatMap((p) => p.data);
  const [loadingAll, setLoadingAll] = React.useState(false);
  if (tools.isPending)
    return (
      <div className="flex flex-col gap-2" data-testid="tools-app-loading">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  if (tools.isError && !tools.data) return <QueryError what={`${app.name} tools`} error={tools.error} onRetry={() => void tools.refetch()} retrying={tools.isFetching} testId="tools-app-error" />;
  if (!rows.length)
    return (
      <p className="py-8 text-center text-sm text-muted-foreground" data-testid="tools-app-empty">
        {search.trim() ? `No ${app.name} tool matches “${search.trim()}”.` : `No ${app.name} tools are added yet.`}
      </p>
    );
  const everyPicked = !tools.hasNextPage && rows.every((t) => t.granted || picked.has(t.id));
  // Select all means every tool the search finds, so the pages not yet loaded are read first.
  const selectAll = async () => {
    if (everyPicked) return setPicked(new Set());
    setLoadingAll(true);
    try {
      let pages = tools.data?.pages ?? [];
      let more = tools.hasNextPage;
      while (more) {
        const next = await tools.fetchNextPage();
        pages = next.data?.pages ?? pages;
        more = next.hasNextPage && !next.isError;
      }
      setPicked(new Set([...picked, ...pages.flatMap((p) => p.data).filter((t) => !t.granted).map((t) => t.id)]));
    } finally {
      setLoadingAll(false);
    }
  };
  const toggle = (id: string) => {
    const next = new Set(picked);
    if (!next.delete(id)) next.add(id);
    setPicked(next);
  };
  return (
    <div className="flex flex-col gap-2">
      <ul className="divide-y rounded-lg border bg-card" data-testid="tools-app-list">
        <li className="flex items-center gap-3 bg-muted/40 px-3 py-2.5">
          <Checkbox id="pick-all" data-testid="tools-app-select-all" checked={everyPicked} disabled={loadingAll} onCheckedChange={() => void selectAll()} />
          <Label htmlFor="pick-all" className="font-medium">
            {loadingAll ? 'Selecting…' : 'Select all'}
          </Label>
        </li>
        {rows.map((t) => (
          <ToolRow key={t.id} tool={t} picked={picked.has(t.id)} onToggle={() => toggle(t.id)} />
        ))}
      </ul>
      {tools.hasNextPage && (
        <Button type="button" variant="outline" size="sm" className="self-center" disabled={tools.isFetchingNextPage} onClick={() => void tools.fetchNextPage()}>
          {tools.isFetchingNextPage ? 'Loading…' : 'Show more tools'}
        </Button>
      )}
    </div>
  );
}

function PickerDialog({ agentId, agentName, onGrant, onClose }: { agentId: string; agentName: string; onGrant: (ids: string[]) => void; onClose: () => void }) {
  // Kept past a remount (a resize can rebuild the page around the dialog), so the step and the selection survive it.
  const kept = memory.get(agentId);
  const [app, setApp] = React.useState<AgentToolApp | null>(kept?.app ?? null);
  const [search, setSearch] = React.useState(kept?.search ?? '');
  const [picked, setPicked] = React.useState<Set<string>>(new Set(kept?.picked ?? []));
  React.useEffect(() => {
    memory.set(agentId, { open: true, app, search, picked: [...picked] });
  }, [agentId, app, search, picked]);
  const tools = useAgentToolAppTools(agentId, app?.id ?? null, { search });
  const open = (a: AgentToolApp | null) => {
    setApp(a);
    setSearch('');
    setPicked(new Set());
  };
  const add = () => {
    onGrant([...picked]);
    onClose();
  };
  return (
    <DialogShell
      open
      onOpenChange={(o) => !o && onClose()}
      size="xl"
      title={app ? `Add ${app.name} tools` : `Add tools to ${agentName}`}
      description={app ? 'Choose the tools this agent may call.' : 'Choose an app, then the tools of it the agent may call.'}
      data-testid="tools-picker-dialog"
      headerExtra={
        <div className="flex items-center gap-2 pt-2">
          {app && (
            <Button type="button" variant="ghost" size="sm" onClick={() => open(null)} data-testid="tools-picker-back">
              <ArrowLeft className="size-4" /> All apps
            </Button>
          )}
          <Input
            data-testid="tools-picker-search"
            aria-label={app ? `Search ${app.name} tools` : 'Search apps and tools'}
            placeholder={app ? `Search ${app.name} tools…` : 'Search apps and tools, e.g. refund'}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="min-w-0 flex-1 bg-card"
          />
        </div>
      }
      footer={
        app ? (
          <div className="flex w-full flex-wrap items-center justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="button" disabled={picked.size === 0} onClick={add} data-testid="tools-app-add">
              {picked.size === 0 ? 'Add tools' : `Add ${plural(picked.size, 'tool')}`}
            </Button>
          </div>
        ) : undefined
      }
    >
      {app ? (
        <div className="flex flex-col gap-3">
          <ConnectStrip agentId={agentId} app={app} onConnected={() => setApp({ ...app, connected: true })} />
          <NotAddedLine app={app} />
          <ToolsStep app={app} search={search} tools={tools} picked={picked} setPicked={setPicked} />
        </div>
      ) : (
        <AppsStep
          agentId={agentId}
          search={search}
          onOpen={(a) => open(a)}
          onAddTool={(id) => onGrant([id])}
        />
      )}
    </DialogShell>
  );
}

/** What an open picker holds, by agent, so it comes back as it was if the page under it is rebuilt. */
const memory = new Map<string, { open: boolean; app: AgentToolApp | null; search: string; picked: string[] }>();

/** Whether the picker is open, remembered as above; closing forgets the step and the selection. */
export function usePickerOpen(agentId: string): [boolean, (open: boolean) => void] {
  const [open, setOpenState] = React.useState(() => memory.get(agentId)?.open ?? false);
  const setOpen = (o: boolean) => {
    if (!o) memory.delete(agentId);
    setOpenState(o);
  };
  return [open, setOpen];
}

/**
 * Add tools to an agent: step one lists the apps (searched on the server, connected first, a search also names the
 * tools it matched), step two lists one app's tools with Select all and one Add. A grant is the page's own save of the
 * stored tool list (`onGrant`), never part of the autosaved draft.
 */
export function AgentToolsPicker({ agentId, agentName, disabled, hidden, open, onOpenChange, onGrant }: { agentId: string; agentName: string; disabled?: boolean; hidden?: boolean; open: boolean; onOpenChange: (open: boolean) => void; onGrant: (ids: string[]) => void }) {
  return (
    <>
      <Button type="button" variant="outline" size="sm" className={cn('bg-card', hidden && 'hidden')} disabled={disabled} onClick={() => onOpenChange(true)} data-testid="agent-tools-picker">
        <Plus className="size-3.5" /> Add tools
      </Button>
      {open && <PickerDialog agentId={agentId} agentName={agentName} onGrant={onGrant} onClose={() => onOpenChange(false)} />}
    </>
  );
}
