'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowRight, CircleCheck, CircleAlert, Plug, Plus, Search, TriangleAlert } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { type AppState, type SystemCard, useSystems } from '@/hooks/systems-queries';
import { plural } from '@/lib/format';
import { cn } from '@/lib/utils';

import { AppsTabs } from './apps-tabs';
import type { ConnectMode } from './connect-system-dialog';

export type { ConnectMode };
type View = 'all' | 'connected' | 'available';

const STATE: Record<AppState, { label: string; className: string; icon?: typeof CircleCheck }> = {
  connected: { label: 'Connected', className: 'border-success/40 bg-success/10 text-success-text', icon: CircleCheck },
  test_failed: { label: 'Signed in, test failed', className: 'border-warning/40 bg-warning/10 text-warning-text', icon: TriangleAlert },
  needs_sign_in: { label: 'Needs sign-in', className: 'border-warning/40 bg-warning/10 text-warning-text', icon: CircleAlert },
  not_installed: { label: 'Not installed', className: 'text-muted-foreground' },
  removed: { label: 'No longer installed', className: 'border-destructive/40 bg-destructive/10 text-destructive', icon: CircleAlert },
};

/** The app's state as a badge, worded the same on its card and its page. */
export function AppStateBadge({ card, testId, withTools }: { card: SystemCard; testId?: string; withTools?: boolean }) {
  if (!card.appState) return null;
  const shown = STATE[card.appState];
  const Icon = shown.icon;
  return (
    <Badge variant="outline" className={shown.className} data-testid={testId}>
      {Icon && <Icon />}
      {card.appState === 'connected' && withTools && card.kind !== 'builtin' ? `Connected · ${plural(card.toolsCount, 'tool')}` : shown.label}
    </Badge>
  );
}

const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

/** The app's page, where its accounts, tools, skills, sign-ins, runs and settings are; a built-in app's is the console
 * page that manages it (its knowledge bases, its mailboxes). */
export const appHref = (s: Pick<SystemCard, 'id' | 'href'>) => s.href ?? `/integrations/apps/${encodeURIComponent(s.id)}`;

/**
 * One app's card: logo, name, tools and how it signs in, one line, its category, its state and one
 * action. The whole card opens the app's page; Connect sits above that link.
 */
function AppCard({ system, onConnect }: { system: SystemCard; onConnect: (s: SystemCard, mode: ConnectMode) => void }) {
  const state = system.appState;
  const failure = state === 'test_failed' ? (system.appStateReason ?? 'no reason given') : null;
  // A removed app has nothing to connect; its page says why its tools stopped.
  const opens = state === 'connected' || state === 'test_failed' || state === 'removed';
  return (
    <Card className="relative min-h-40 gap-3 transition-all hover:border-primary/40 hover:shadow-md" data-testid={`system-${system.id}`} data-state={state}>
      <CardHeader className="flex flex-row items-center gap-2.5 px-4">
        <Avatar className="size-9 rounded-md">
          {system.logo && <AvatarImage src={system.logo} alt="" />}
          <AvatarFallback className="rounded-md text-xs font-semibold">{initials(system.name)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <CardTitle className="truncate text-base">
            {/* Stretched over the card, so the whole card opens the app's page. */}
            <Link href={appHref(system)} className="after:absolute after:inset-0 after:rounded-xl focus-visible:outline-none" data-testid={`card-link-${system.id}`}>
              {system.name}
            </Link>
          </CardTitle>
          <p className="truncate text-xs text-muted-foreground">
            {plural(system.toolsCount, 'tool')}
            {system.kindLabel ? ` · ${system.kindLabel}` : ''}
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
        {state === 'removed' && (
          <p className="line-clamp-2 text-xs text-destructive" data-testid={`system-${system.id}-removed`}>
            {system.appStateReason}
          </p>
        )}
        {failure && (
          <p className="line-clamp-2 text-xs text-warning-text" data-testid={`system-${system.id}-test-failed`}>
            Signed in, but a test call failed: {failure}
          </p>
        )}
        <div className="mt-auto flex items-center justify-between gap-2">
          <AppStateBadge card={system} withTools testId={`system-${system.id}-state`} />
          {opens ? (
            <span className="inline-flex items-center gap-1 text-sm font-medium" data-testid={`open-${system.id}`} data-href={appHref(system)}>
              Open
              <ArrowRight className="size-4" />
            </span>
          ) : system.mayManage ? (
            <Button size="sm" variant="outline" className="relative z-10" onClick={() => onConnect(system, 'connect')} data-testid={`connect-${system.id}`}>
              Connect
            </Button>
          ) : (
            // Only a team admin connects an app; anyone else is told why rather than shown a dead button.
            <span className="text-xs text-muted-foreground" data-testid={`connect-${system.id}-why`}>
              A team admin connects it
            </span>
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

function Section({ title, systems, onConnect, testId }: { title: string; systems: SystemCard[]; onConnect: (s: SystemCard, mode: ConnectMode) => void; testId: string }) {
  if (!systems.length) return null;
  return (
    <section className="flex flex-col gap-2" data-testid={testId}>
      <h2 className="text-sm font-semibold text-muted-foreground">
        {title} · {systems.length}
      </h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {systems.map((s) => (
          <AppCard key={s.id} system={s} onConnect={onConnect} />
        ))}
      </div>
    </section>
  );
}

/**
 * The apps catalog: the team's connected apps first, then the ones it may connect; one search, a
 * category filter, and Connected only and Available only. Read from GET /v1/apps, each card already joined.
 */
export function SystemsGrid({ onConnect, onNew }: { onConnect: (s: SystemCard, mode: ConnectMode) => void; onNew: () => void }) {
  const systems = useSystems();
  const [view, setView] = React.useState<View>('all');
  const [category, setCategory] = React.useState<string | null>(null);
  const [q, setQ] = React.useState('');
  const all = [...(systems.data ?? [])].sort((a, b) => Number(b.kind === 'plugin') - Number(a.kind === 'plugin'));
  const categories = [...new Set(all.map((s) => s.category).filter((c): c is string => Boolean(c)))].sort();
  // Connected lists the apps the team turned on, whatever their account's state; the API decides which those are.
  const isOn = (card: SystemCard) => Boolean(card.appState) && card.appState !== 'not_installed';
  const shown = all.filter(
    (s) =>
      (view === 'all' || (view === 'connected') === isOn(s)) &&
      (!category || s.category === category) &&
      (!q || `${s.name} ${s.description ?? ''} ${s.category ?? ''}`.toLowerCase().includes(q.toLowerCase())),
  );
  const filtered = Boolean(q) || view !== 'all' || Boolean(category);
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
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <div className="relative w-full max-w-sm">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search apps" className="pl-9" aria-label="Search apps" />
          </div>
          {systems.data && (
            <span className="shrink-0 text-sm text-muted-foreground" data-testid="apps-count">
              {shown.length} of {all.length}
            </span>
          )}
        </div>
        {systems.data && (
          <div className="flex flex-wrap items-center gap-1.5" data-testid="apps-tags">
            <FilterBadge on={view === 'connected'} onClick={() => toggle('connected')} testId="filter-connected">
              Connected only
            </FilterBadge>
            <FilterBadge on={view === 'available'} onClick={() => toggle('available')} testId="filter-available">
              Available only
            </FilterBadge>
            {categories.length > 0 && <span className="mx-1 h-5 w-px bg-border" aria-hidden />}
            {categories.map((c) => (
              <FilterBadge key={c} on={category === c} onClick={() => setCategory((cur) => (cur === c ? null : c))} testId={`filter-category-${c}`}>
                {c}
              </FilterBadge>
            ))}
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
          onClear={() => (setQ(''), setView('all'), setCategory(null))}
          createLabel="Add custom app"
          onCreate={onNew}
          description="Your platform admin installs apps; you can add your own app now."
        />
      ) : (
        <div className="flex flex-col gap-6" data-testid="systems-grid">
          <Section title="Connected" systems={shown.filter(isOn)} onConnect={onConnect} testId="apps-connected" />
          <Section title="Available" systems={shown.filter((app) => !isOn(app))} onConnect={onConnect} testId="apps-available" />
        </div>
      )}
    </PageLayout>
  );
}
