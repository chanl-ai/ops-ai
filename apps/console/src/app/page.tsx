'use client';

import * as React from 'react';
import Link from 'next/link';
import { CalendarClock, CheckCheck, CirclePlay, Gift, LayoutDashboard, Search, UserCheck } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item';
import { useChangelog } from '@/hooks/use-changelog';
import { useOverview } from '@/hooks/queries';
import { relativeTime } from '@/lib/format';
import { readOverview } from '@/lib/overview';

interface Row {
  id: string;
  title: string;
  detail: string;
  href?: string;
}

const match = (q: string, r: Row) => !q || `${r.title} ${r.detail}`.toLowerCase().includes(q.toLowerCase());

/**
 * What is waiting (c-552): Human Tasks waiting for you, runs in flight, cases due and What's new, under one search. Every
 * number and row comes from the one overview response (no list joined here); a row opens its page as it ships.
 */
export default function OverviewPage() {
  const query = useOverview();
  const changelog = useChangelog();
  const [q, setQ] = React.useState('');
  const o = query.data && readOverview(query.data);

  const widgets = o && [
    {
      id: 'tasks',
      title: 'Human Tasks waiting for you',
      icon: UserCheck,
      count: o.counts.waitingForMe,
      all: '/reviews',
      none: 'Nothing is waiting for you.',
      rows: o.waitingForMe.map((t): Row => ({ id: t.id, title: t.title, detail: `${t.workflowName ? `${t.workflowName} · ` : ''}waiting since ${relativeTime(t.createdAt)}`, href: `/reviews?review=${t.id}` })),
    },
    {
      id: 'runs',
      title: 'Runs in flight',
      icon: CirclePlay,
      count: o.counts.runsInFlight,
      all: '/workflows/runs',
      none: 'No runs in flight.',
      rows: o.runsInFlight.map((r): Row => ({ id: r.id, title: r.subject, detail: `${r.state === 'waiting' ? 'Waiting on a person' : 'Running'} · started ${relativeTime(r.startedAt)}`, href: `/workflows/runs/${r.id}` })),
    },
    {
      id: 'cases',
      title: 'Cases due',
      icon: CalendarClock,
      count: o.counts.casesDue,
      all: '/cases',
      none: 'No cases due today.',
      rows: o.casesDue.map((c): Row => ({ id: c.id, title: c.subject, detail: `${c.customerName ? `${c.customerName} · ` : ''}${c.resolutionDueAt && new Date(c.resolutionDueAt) < new Date() ? 'past its deadline' : 'due today'}`, href: `/cases/${c.id}` })),
    },
    {
      id: 'news',
      title: 'What’s new',
      icon: Gift,
      count: undefined,
      all: undefined,
      none: 'Nothing new yet.',
      rows: changelog.entries.slice(0, 5).map((e): Row => ({ id: e.id, title: e.title, detail: e.date })),
    },
  ];

  return (
    <PageLayout icon={LayoutDashboard} title="Overview" description="What is waiting for you">
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={6} />
      ) : query.isError || !widgets ? (
        <QueryError what="the overview" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="relative w-full sm:max-w-xs">
            <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search what is waiting" aria-label="Search what is waiting" className="pl-8" data-testid="overview-search" />
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {widgets.map((w) => {
              const rows = w.rows.filter((r) => match(q, r));
              return (
                <Card key={w.id} className="min-w-0 gap-0 py-0" data-testid={`overview-${w.id}`}>
                  <CardHeader className="border-b py-3 [.border-b]:pb-3">
                    <CardTitle className="flex items-center gap-2 text-sm">
                      <w.icon className="size-4 text-muted-foreground" />
                      {w.title}
                      {w.count !== undefined && (
                        <Badge variant="secondary" className="tabular-nums" data-testid={`overview-${w.id}-count`}>
                          {w.count}
                        </Badge>
                      )}
                    </CardTitle>
                    {w.all && (
                      <CardAction>
                        <Button asChild variant="ghost" size="sm">
                          <Link href={w.all}>Open all</Link>
                        </Button>
                      </CardAction>
                    )}
                  </CardHeader>
                  <CardContent className="px-0">
                    {!w.rows.length ? (
                      <EmptyState icon={CheckCheck} title={w.none} description="" />
                    ) : !rows.length ? (
                      <p className="px-6 py-6 text-center text-sm text-muted-foreground">No match for “{q}”.</p>
                    ) : (
                      <ItemGroup className="divide-y">
                        {rows.map((r) =>
                          r.href ? (
                            <Item key={r.id} asChild size="sm" className="rounded-none px-6 hover:bg-muted/50">
                              <Link href={r.href} data-testid={`overview-${w.id}-row`}>
                                <ItemContent className="min-w-0">
                                  <ItemTitle className="w-full truncate">{r.title}</ItemTitle>
                                  <ItemDescription className="truncate">{r.detail}</ItemDescription>
                                </ItemContent>
                              </Link>
                            </Item>
                          ) : (
                            <Item key={r.id} size="sm" className="rounded-none px-6">
                              <ItemContent className="min-w-0">
                                <ItemTitle className="w-full truncate">{r.title}</ItemTitle>
                                <ItemDescription className="truncate">{r.detail}</ItemDescription>
                              </ItemContent>
                            </Item>
                          ),
                        )}
                      </ItemGroup>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      )}
    </PageLayout>
  );
}
