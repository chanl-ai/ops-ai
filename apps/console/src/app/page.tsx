'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowRight, CheckCheck, Inbox, LayoutDashboard, UserCheck } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { RiskBadge, SlaText } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { RowOpen } from '@/components/shared/row-open';
import { useOverview } from '@/hooks/queries';
import { money } from '@/lib/format';

/**
 * What is waiting on a person: the Reviews count and the Cases "Needs a person" view (docs/console/strategy.md).
 * Agent performance tiles return once metering measures them.
 */
export default function OverviewPage() {
  const router = useRouter();
  const query = useOverview();
  const o = query.data;

  return (
    <PageLayout icon={LayoutDashboard} title="Overview" description="What is waiting on a person">
      {query.isPending ? (
        <PageSkeleton statCards={2} tableRows={6} />
      ) : query.isError || !o ? (
        <QueryError what="the overview" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <div className="flex flex-col gap-4">
          <StatCardGrid columns={2}>
            <Link href="/reviews" className="rounded-xl focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none" data-testid="overview-reviews">
              <StatCard label="Waiting on review" value={o.openReviews} icon={Inbox} className="h-full transition-colors hover:border-primary/40" footer={{ text: `${o.overdueReviews} past SLA`, subtext: 'Runs stay paused until decided' }} />
            </Link>
            <Link href="/cases" className="rounded-xl focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none" data-testid="overview-cases">
              <StatCard
                label="Needs a person"
                value={o.cases.open}
                icon={UserCheck}
                className="h-full transition-colors hover:border-primary/40"
                footer={{ text: `${o.cases.breaching} past SLA`, subtext: `${o.cases.awaitingApproval} with actions to approve` }}
              />
            </Link>
          </StatCardGrid>

        <Card className="gap-3">
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
                      <TableRow
                        key={r.id}
                        className="cursor-pointer"
                        onClick={(e) => !(e.target as HTMLElement).closest('a[href]') && router.push(`/reviews?review=${r.id}`)}
                      >
                        <TableCell className="pl-6">
                          <RowOpen href={`/reviews?review=${r.id}`}>
                            <div className="font-medium">{r.title}</div>
                            <div className="text-xs text-muted-foreground">
                              <span className="font-mono">{r.id}</span> · {r.workflowName}
                            </div>
                          </RowOpen>
                        </TableCell>
                        <TableCell>
                          <RiskBadge risk={r.risk} />
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{r.amount != null ? money(r.amount, r.currency) : '—'}</TableCell>
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
        </div>
      )}
    </PageLayout>
  );
}
