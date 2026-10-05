'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AlertCircle, ArrowRight, Bot, CheckCheck, Inbox, LayoutDashboard, Mail } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts';

import { PageLayout } from '@/components/page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { RiskBadge, SlaText } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { type ChartConfig, ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useOverview } from '@/hooks/queries';
import { count, money, pct } from '@/lib/format';
import { cn } from '@/lib/utils';

const chartConfig = {
  completedByAgent: { label: 'Completed by agent', color: 'var(--chart-1)' },
  sentToReview: { label: 'Sent to review', color: 'var(--chart-4)' },
} satisfies ChartConfig;

export default function OverviewPage() {
  const router = useRouter();
  const query = useOverview();
  const o = query.data;

  return (
    <PageLayout icon={LayoutDashboard} title="Overview" description="What the agents did today and what is waiting on a person">
      {query.isPending ? (
        <PageSkeleton statCards={4} tableRows={6} />
      ) : query.isError || !o ? (
        <QueryError what="the overview" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <div className="flex flex-col gap-4">
          <StatCardGrid columns={4}>
            <StatCard label="Waiting on review" value={o.openReviews} icon={Inbox} footer={{ text: `${o.overdueReviews} past SLA`, subtext: 'Runs stay paused until decided' }} />
            <StatCard
              label="Agent tasks · 24h"
              value={count(o.tasks24h)}
              icon={Bot}
              trend={o.tasks24h ? { value: `${Math.abs(o.tasksTrendPct)}%`, direction: o.tasksTrendPct >= 0 ? 'up' : 'down', isPositive: true } : undefined}
              footer={{ text: `${o.liveAgents} live agents`, subtext: 'vs. previous 24h' }}
            />
            <StatCard label="Completed without review" value={pct(o.autoResolvedRate)} icon={CheckCheck} footer={{ text: 'Finished with no gate hit', subtext: 'Weighted by volume' }} />
            <Link href="/cases" className="rounded-xl focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none" data-testid="overview-cases">
              <StatCard
                label="Open email cases"
                value={o.cases?.open ?? 0}
                icon={Mail}
                className="h-full transition-colors hover:border-primary/40"
                footer={{ text: `${o.cases?.breaching ?? 0} past SLA`, subtext: `${o.cases?.awaitingApproval ?? 0} waiting on an approval` }}
              />
            </Link>
          </StatCardGrid>

          <div className="grid grid-cols-1 gap-4 @5xl/main:grid-cols-5">
            <Card className="gap-3 @5xl/main:col-span-3">
              <CardHeader>
                <CardTitle>Needs a decision</CardTitle>
                <CardDescription>Open reviews, soonest SLA first</CardDescription>
                <CardAction>
                  <Button variant="ghost" size="sm" asChild>
                    <Link href="/reviews">
                      Open queue <ArrowRight className="size-3.5" />
                    </Link>
                  </Button>
                </CardAction>
              </CardHeader>
              <CardContent className="px-0">
                {o.urgentReviews.length === 0 ? (
                  <EmptyState icon={CheckCheck} title="Nothing waiting" description="Every paused run has been decided." />
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="pl-6">Request</TableHead>
                        <TableHead>Risk</TableHead>
                        <TableHead className="text-right">Amount</TableHead>
                        <TableHead className="pr-6 text-right">SLA</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {o.urgentReviews.map((r) => (
                        <TableRow key={r.id} className="cursor-pointer" onClick={() => router.push(`/reviews?review=${r.id}`)}>
                          <TableCell className="pl-6">
                            <div className="font-medium">{r.title}</div>
                            <div className="text-xs text-muted-foreground">
                              <span className="font-mono">{r.id}</span> · {r.workflowName}
                            </div>
                          </TableCell>
                          <TableCell>
                            <RiskBadge risk={r.risk} />
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{r.amount !== undefined ? money(r.amount, r.currency) : '—'}</TableCell>
                          <TableCell className="pr-6 text-right">
                            <SlaText minutes={r.slaMinutes} open />
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>

            <Card className="gap-3 @5xl/main:col-span-2">
              <CardHeader>
                <CardTitle>Agent tasks · 7 days</CardTitle>
                <CardDescription>Completed by agent vs. sent to a person</CardDescription>
              </CardHeader>
              <CardContent>
                <ChartContainer config={chartConfig} className="aspect-auto h-64 w-full">
                  <AreaChart data={o.throughput7d} margin={{ left: 0, right: 8, top: 8 }}>
                    <CartesianGrid vertical={false} />
                    <XAxis dataKey="day" tickLine={false} axisLine={false} tickMargin={8} fontSize={11} />
                    <YAxis tickLine={false} axisLine={false} width={40} fontSize={11} />
                    <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
                    <ChartLegend content={<ChartLegendContent />} />
                    <Area dataKey="sentToReview" type="monotone" stackId="a" fill="var(--color-sentToReview)" fillOpacity={0.35} stroke="var(--color-sentToReview)" />
                    <Area dataKey="completedByAgent" type="monotone" stackId="a" fill="var(--color-completedByAgent)" fillOpacity={0.25} stroke="var(--color-completedByAgent)" />
                  </AreaChart>
                </ChartContainer>
              </CardContent>
            </Card>
          </div>

          <Card className="gap-3">
            <CardHeader>
              <CardTitle>Workflow health</CardTitle>
              <CardDescription>Last 24 hours</CardDescription>
            </CardHeader>
            <CardContent className="px-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-6">Workflow</TableHead>
                    <TableHead className="text-right">Runs</TableHead>
                    <TableHead>Sent to review</TableHead>
                    <TableHead className="pr-6 text-right">Open now</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {o.workflowHealth.map((w) => {
                    const rate = w.runs24h ? w.reviewed24h / w.runs24h : 0;
                    return (
                      <TableRow key={w.id} className="cursor-pointer" onClick={() => router.push(`/workflows/${w.id}`)}>
                        <TableCell className="pl-6 font-medium">{w.name}</TableCell>
                        <TableCell className="text-right tabular-nums">{count(w.runs24h)}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
                              <div className={cn('h-full rounded-full', rate > 0.3 ? 'bg-amber-500' : 'bg-primary')} style={{ width: `${rate * 100}%` }} />
                            </div>
                            <span className="text-xs tabular-nums text-muted-foreground">{pct(rate)}</span>
                          </div>
                        </TableCell>
                        <TableCell className="pr-6 text-right tabular-nums">
                          {w.openReviews > 0 ? (
                            <span className="inline-flex items-center gap-1">
                              {w.openReviews > 2 && <AlertCircle className="size-3.5 text-amber-600" />}
                              {w.openReviews}
                            </span>
                          ) : (
                            0
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}
    </PageLayout>
  );
}
