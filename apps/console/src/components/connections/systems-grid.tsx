'use client';

import * as React from 'react';
import Link from 'next/link';
import { Cable, CircleCheck, CircleX, ExternalLink, Plus, Search } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { type SystemCard, useSystems } from '@/hooks/systems-queries';
import { cn } from '@/lib/utils';

import type { ConnectMode } from './connect-system-dialog';

export type { ConnectMode };
type View = 'all' | 'connected' | 'available';
const EVERY = 'every';

const connected = (s: SystemCard) => Object.values(s.environments).some((e) => e?.set);
const failing = (s: SystemCard) => Object.values(s.environments).some((e) => e?.health?.status === 'failed');
const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

/** One environment's state from its last test: Working, Failing, or Not set with no keys. */
function EnvBadge({ env, system }: { env: string; system: SystemCard }) {
  const e = system.environments[env];
  const state = !e?.set ? 'unset' : e.health?.status === 'failed' ? 'failed' : e.health?.status === 'ok' ? 'ok' : 'set';
  return (
    <Badge
      variant="outline"
      className={cn(
        state === 'ok' && 'border-success/40 bg-success/10 text-success-text',
        state === 'failed' && 'border-destructive/40 bg-destructive/10 text-destructive',
      )}
      data-testid={`system-${system.id}-${env}`}
    >
      {state === 'ok' && <CircleCheck />}
      {state === 'failed' && <CircleX />}
      {e?.label ?? env} · {state === 'ok' ? 'Working' : state === 'failed' ? 'Failing' : state === 'set' ? 'Not tested' : 'Not set'}
    </Badge>
  );
}

function SystemCardView({ system, onConnect }: { system: SystemCard; onConnect: (s: SystemCard, mode: ConnectMode) => void }) {
  const isConnected = connected(system);
  return (
    <Card className="gap-3 py-4" data-testid={`system-${system.id}`}>
      <CardHeader className="flex flex-row items-start gap-3 px-4">
        <Avatar className="size-9 rounded-md">
          {system.logo && <AvatarImage src={system.logo} alt="" />}
          <AvatarFallback className="rounded-md text-xs font-semibold">{initials(system.name)}</AvatarFallback>
        </Avatar>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="truncate text-sm font-semibold">{system.name}</span>
            {system.kind === 'plugin' && <Badge variant="outline">Plugin</Badge>}
          </div>
          <span className="truncate text-xs text-muted-foreground">
            {system.toolsCount} tools{system.kindLabel ? ` · ${system.kindLabel}` : ''}
          </span>
        </div>
        {system.category && <Badge variant="secondary">{system.category}</Badge>}
      </CardHeader>
      <CardContent className="flex flex-col gap-3 px-4">
        {system.description && <p className="line-clamp-2 text-sm text-muted-foreground">{system.description}</p>}
        <div className="flex flex-wrap gap-1.5">
          {Object.keys(system.environments).map((env) => (
            <EnvBadge key={env} env={env} system={system} />
          ))}
        </div>
      </CardContent>
      <CardFooter className="mt-auto flex flex-wrap items-center gap-2 border-t px-4 pt-3">
        {isConnected && system.connectionId ? (
          <Button size="sm" variant="outline" asChild>
            <Link href={`/tools/connections/${encodeURIComponent(system.connectionId)}`}>Open</Link>
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={() => onConnect(system, 'connect')} disabled={!system.mayManage} data-testid={`connect-${system.id}`}>
            Connect
          </Button>
        )}
        {isConnected && failing(system) && system.mayManage && (
          <Button size="sm" variant="ghost" onClick={() => onConnect(system, 'edit')}>
            Fix keys
          </Button>
        )}
        <span className="flex-1" />
        {system.docsUrl && (
          <Button size="sm" variant="link" className="h-auto px-0 text-xs text-muted-foreground" asChild>
            <a href={system.docsUrl} target="_blank" rel="noopener noreferrer">
              <ExternalLink />
              Docs
            </a>
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}

/**
 * Connections as a grid of the team's systems (c-580), read from GET /v1/systems so each card arrives joined: a
 * plugin, a connection or a module, with its details and each environment's health. One search, a category filter and
 * All, Connected, Not connected, so a long list of systems stays easy to scan.
 */
export function SystemsGrid({ onConnect, onNew }: { onConnect: (s: SystemCard, mode: ConnectMode) => void; onNew: () => void }) {
  const systems = useSystems();
  const [view, setView] = React.useState<View>('all');
  const [q, setQ] = React.useState('');
  const [category, setCategory] = React.useState(EVERY);
  const all = systems.data ?? [];
  const categories = [...new Set(all.map((s) => s.category).filter((c): c is string => Boolean(c)))].sort();
  const shown = all.filter(
    (s) =>
      (view === 'all' || (view === 'connected') === Boolean(connected(s))) &&
      (category === EVERY || s.category === category) &&
      (!q || `${s.name} ${s.description ?? ''} ${s.category ?? ''}`.toLowerCase().includes(q.toLowerCase())),
  );
  const count = (v: View) => (systems.data ? all.filter((s) => v === 'all' || (v === 'connected') === Boolean(connected(s))).length : undefined);
  const label = (text: string, n: number | undefined) => (n == null ? text : `${text} · ${n}`);
  const filtered = Boolean(q) || category !== EVERY || view !== 'all';
  return (
    <PageLayout
      icon={Cable}
      title="Connections"
      description="Every system the team signs in to, with its keys for test and production."
      contentClassName="flex flex-col gap-4"
      actions={
        <Button onClick={onNew} data-testid="connect-system">
          <Plus />
          Connect a system
        </Button>
      }
    >
      <div className="flex flex-col gap-3 md:flex-row">
        <Tabs value={view} onValueChange={(v) => setView(v as View)}>
          <TabsList aria-label="Which systems">
            <TabsTrigger value="all">{label('All', count('all'))}</TabsTrigger>
            <TabsTrigger value="connected">{label('Connected', count('connected'))}</TabsTrigger>
            <TabsTrigger value="available">{label('Not connected', count('available'))}</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 sm:justify-end">
          <div className="relative min-w-0 flex-1 sm:max-w-xs">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search systems" className="pl-8" aria-label="Search systems" />
          </div>
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger aria-label="Category" className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={EVERY}>Every category</SelectItem>
              {categories.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {systems.isError ? (
        <QueryError what="your systems" error={systems.error} onRetry={() => systems.refetch()} retrying={systems.isFetching} />
      ) : systems.isPending ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : !shown.length ? (
        <ListEmpty
          icon={Cable}
          noun="systems"
          filtered={filtered && all.length > 0}
          onClear={() => (setQ(''), setCategory(EVERY), setView('all'))}
          createLabel="Connect a system"
          onCreate={onNew}
          description="Connect a system with its keys, or import its tools first and connect it from there."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3" data-testid="systems-grid">
          {shown.map((s) => (
            <SystemCardView key={s.id} system={s} onConnect={onConnect} />
          ))}
        </div>
      )}
    </PageLayout>
  );
}
