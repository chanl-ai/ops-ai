'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowRight, CircleCheck, Plug, Plus, Search } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { type SystemCard, useSystems } from '@/hooks/systems-queries';
import { plural } from '@/lib/format';
import { cn } from '@/lib/utils';

import { AppsTabs } from './apps-tabs';
import type { ConnectMode } from './connect-system-dialog';

export type { ConnectMode };
type View = 'all' | 'connected' | 'available';

// Connected reads the app's state, as its page does: an account signed in or a key that passed its test, never settings
// saved alone. A plugin the team turned off (Turn off, group K) offers Connect again; its accounts stay for later.
const connected = (s: SystemCard) =>
  s.plugin?.teamOn !== false && (s.state ? s.state === 'connected' || s.state === 'expired' || s.state === 'refused' : Object.values(s.environments).some((e) => e?.set));
const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

/** The app's page, where its accounts, tools, skills, sign-ins, runs and settings are (c-607); a built-in app's is the
 * console page that manages it (its knowledge bases, its mailboxes). */
export const appHref = (s: SystemCard) => s.href ?? `/integrations/apps/${encodeURIComponent(s.id)}`;

// Only Ops AI's own apps carry a tag; how an app was installed is never named on screen (owner, 11-01: one word, App).

/** One app's card: logo, name, tools and how it signs in, one line, its category. */
function AppCard({ system, onConnect }: { system: SystemCard; onConnect: (s: SystemCard, mode: ConnectMode) => void }) {
  const isConnected = system.kind === 'builtin' || connected(system);
  return (
    <Card className="min-h-40 gap-3 py-4 transition-all hover:border-primary/40 hover:shadow-md" data-testid={`system-${system.id}`}>
      <CardHeader className="flex flex-row items-center gap-2.5 px-4">
        <Avatar className="size-9 rounded-md">
          {system.logo && <AvatarImage src={system.logo} alt="" />}
          <AvatarFallback className="rounded-md text-xs font-semibold">{initials(system.name)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <CardTitle className="truncate text-base">{system.name}</CardTitle>
          <p className="truncate text-xs text-muted-foreground">
            {plural(system.toolsCount, 'tool')}{system.kindLabel ? ` · ${system.kindLabel}` : ''}
          </p>
        </div>
        {system.kind === 'builtin' && (
          <Badge variant="outline" className="ml-auto shrink-0">
            Built in
          </Badge>
        )}
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3 px-4">
        {system.description && <CardDescription className="line-clamp-1">{system.description}</CardDescription>}
        {system.category && system.kind !== 'builtin' && (
          <div>
            <Badge variant="secondary">{system.category}</Badge>
          </div>
        )}
        <div className="mt-auto flex items-center justify-between gap-2">
          {isConnected ? (
            <>
              <Badge variant="outline" className="border-success/40 bg-success/10 text-success-text" data-testid={`system-${system.id}-status`}>
                <CircleCheck />
                Connected · {plural(system.toolsCount, 'tool')}
              </Badge>
              <Button size="sm" variant="ghost" asChild>
                <Link href={appHref(system)} data-testid={`open-${system.id}`}>
                  Open
                  <ArrowRight />
                </Link>
              </Button>
            </>
          ) : (
            <>
              {/* Only a team admin connects an app; anyone else is told why rather than shown a dead button. */}
              {system.mayManage ? <span /> : <span className="text-xs text-muted-foreground" data-testid={`connect-${system.id}-why`}>A team admin connects it</span>}
              <Button size="sm" variant="outline" onClick={() => onConnect(system, 'connect')} disabled={!system.mayManage} title={system.mayManage ? undefined : 'Only a team admin connects apps'} data-testid={`connect-${system.id}`}>
                Connect
              </Button>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/** A filter drawn as a badge that toggles. */
function FilterBadge({ on, onClick, children, testId }: { on: boolean; onClick: () => void; children: React.ReactNode; testId?: string }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={on} data-testid={testId}>
      <Badge variant={on ? 'default' : 'outline'} className={cn('cursor-pointer', !on && 'hover:border-primary/30 hover:bg-primary/10 hover:text-primary')}>
        {children}
      </Badge>
    </button>
  );
}

/**
 * Connections as an apps catalog (c-607), read from GET /v1/systems so each card arrives joined: plugins first,
 * then the team's own apps. One search, with Connected only and Available only.
 */
export function SystemsGrid({ onConnect, onNew }: { onConnect: (s: SystemCard, mode: ConnectMode) => void; onNew: () => void }) {
  const systems = useSystems();
  const [view, setView] = React.useState<View>('all');
  const [q, setQ] = React.useState('');
  const all = [...(systems.data ?? [])].sort((a, b) => Number(b.kind === 'plugin') - Number(a.kind === 'plugin'));
  const shown = all.filter(
    (s) =>
      (view === 'all' || (view === 'connected') === Boolean(connected(s))) &&
      (!q || `${s.name} ${s.description ?? ''} ${s.category ?? ''}`.toLowerCase().includes(q.toLowerCase())),
  );
  const filtered = Boolean(q) || view !== 'all';
  const toggle = (v: View) => setView((cur) => (cur === v ? 'all' : v));
  return (
    <PageLayout
      icon={Plug}
      title="Apps"
      description="Browse and connect the apps your agents and workflows use."
      tabs={<AppsTabs />}
      contentClassName="flex flex-col gap-4"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setView('connected')} data-testid="connected-apps">
            Connected apps
            <ArrowRight />
          </Button>
          <Button size="sm" onClick={onNew} data-testid="connect-system">
            <Plus />
            Add custom app
          </Button>
        </div>
      }
    >
      <div className="flex items-center gap-3">
        <div className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search apps" className="pl-9" aria-label="Search apps" />
        </div>
        {systems.data && (
          <span className="text-sm text-muted-foreground" data-testid="apps-count">
            {shown.length} of {all.length}
          </span>
        )}
        {/* One grid as the catalog frame: Connected only and Available only narrow it; search covers the category. */}
        {systems.data && (
          <div className="ml-auto flex items-center gap-1.5" data-testid="apps-tags">
            <FilterBadge on={view === 'connected'} onClick={() => toggle('connected')} testId="filter-connected">
              Connected only
            </FilterBadge>
            <FilterBadge on={view === 'available'} onClick={() => toggle('available')} testId="filter-available">
              Available only
            </FilterBadge>
          </div>
        )}
      </div>
      {/* A first answer that failed shows the error with Retry at once, not a skeleton while the retries run. */}
      {!systems.data && (systems.isError || systems.failureCount > 0) ? (
        <QueryError what="your apps" error={systems.error ?? systems.failureReason} onRetry={() => systems.refetch()} retrying={systems.isFetching} />
      ) : systems.isPending ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : !shown.length ? (
        <ListEmpty
          icon={Plug}
          noun="apps"
          filtered={filtered && all.length > 0}
          onClear={() => (setQ(''), setView('all'))}
          createLabel="Add custom app"
          onCreate={onNew}
          description="Your platform admin installs apps; you can add your own app now."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3" data-testid="systems-grid">
          {shown.map((s) => (
            <AppCard key={s.id} system={s} onConnect={onConnect} />
          ))}
        </div>
      )}
    </PageLayout>
  );
}
