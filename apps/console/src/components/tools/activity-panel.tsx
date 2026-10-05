'use client';

import Link from 'next/link';
import { Area, AreaChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';

import { ApprovalCell, CallStatusText } from '@/components/logs/log-meta';
import { Section, StatTile } from '@/components/shared/surface';
import { type ChartConfig, ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { count, ms, relativeTime } from '@/lib/format';
import type { ModuleActivity, ToolModule } from '@/lib/types/tool-modules';

import { pctText } from './module-meta';

const shortDay = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString('en-CA', { month: 'short', day: 'numeric' });
const callsConfig = { ok: { label: 'Succeeded', color: 'var(--chart-1)' }, errors: { label: 'Failed', color: 'var(--destructive)' } } satisfies ChartConfig;
const latencyConfig = { p95Ms: { label: 'p95 latency', color: 'var(--chart-2)' } } satisfies ChartConfig;

/**
 * Calls over 14 days with failures stacked on top (the shape shows when failures started),
 * p95 latency, and the latest calls with a way into the full log.
 */
export function ActivityPanel({ module, activity }: { module: ToolModule; activity: ModuleActivity }) {
  const data = activity.days.map((d) => ({ date: d.date, ok: Math.max(0, d.count - d.errors), errors: d.errors, p95Ms: d.p95Ms }));
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Calls · 24h" value={count(module.calls24h)} />
        <StatTile label="Error rate · 24h" value={pctText(module.errorRate)} tone={module.errorRate >= 0.02 ? 'bad' : 'default'} />
        <StatTile label="p95 latency" value={module.p95Ms ? ms(module.p95Ms) : '—'} />
        <StatTile label="Denied · 24h" value={count(activity.denied24h)} tone={activity.denied24h ? 'warn' : 'default'} hint="Refused at the gateway" />
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Section title="Calls per day" description="Last 14 days">
          <ChartContainer config={callsConfig} className="aspect-auto h-52 w-full">
            <AreaChart accessibilityLayer data={data} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="date" tickLine={false} axisLine={false} tickMargin={8} minTickGap={32} fontSize={11} tickFormatter={shortDay} />
              <YAxis tickLine={false} axisLine={false} width={44} fontSize={11} tickFormatter={(v: number) => count(v)} />
              <ChartTooltip cursor={false} content={<ChartTooltipContent indicator="dot" labelFormatter={(l) => shortDay(String(l))} />} />
              <ChartLegend content={<ChartLegendContent />} />
              <Area dataKey="ok" type="natural" fill="var(--color-ok)" stroke="var(--color-ok)" stackId="calls" fillOpacity={0.4} />
              <Area dataKey="errors" type="natural" fill="var(--color-errors)" stroke="var(--color-errors)" stackId="calls" fillOpacity={0.4} />
            </AreaChart>
          </ChartContainer>
        </Section>
        <Section title="p95 latency" description="Per day, in milliseconds">
          <ChartContainer config={latencyConfig} className="aspect-auto h-52 w-full">
            <LineChart accessibilityLayer data={data} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="date" tickLine={false} axisLine={false} tickMargin={8} minTickGap={32} fontSize={11} tickFormatter={shortDay} />
              <YAxis tickLine={false} axisLine={false} width={44} fontSize={11} />
              <ChartTooltip cursor={false} content={<ChartTooltipContent indicator="line" labelFormatter={(l) => shortDay(String(l))} />} />
              <Line dataKey="p95Ms" type="monotone" stroke="var(--color-p95Ms)" strokeWidth={2} dot={false} />
            </LineChart>
          </ChartContainer>
        </Section>
      </div>
      <Section
        title="Recent calls"
        description="Allowed and denied, as the gateway logged them"
        actions={
          <Link href={`/logs/tool-calls?q=${encodeURIComponent(module.system)}`} className="text-sm font-medium underline-offset-4 hover:underline">
            Open in the tool call log
          </Link>
        }
        flush
      >
        {!activity.recent.length ? (
          <p className="px-4 py-8 text-center text-sm text-muted-foreground">No calls in the last 7 days.</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Operation</TableHead>
                  <TableHead>Workflow</TableHead>
                  <TableHead>Record</TableHead>
                  <TableHead>Approval</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Latency</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activity.recent.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">{relativeTime(c.at)}</TableCell>
                    <TableCell>
                      <code className="font-mono text-xs">{c.target}</code>
                    </TableCell>
                    <TableCell className="text-sm whitespace-nowrap">
                      {c.workflowName}
                      <div className="font-mono text-[11px] text-muted-foreground">{c.caseId ?? c.runId}</div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{c.record ?? '—'}</TableCell>
                    <TableCell>
                      <ApprovalCell approval={c.approval} />
                    </TableCell>
                    <TableCell>
                      <CallStatusText status={c.status} />
                    </TableCell>
                    <TableCell className="text-right text-xs tabular-nums">{ms(c.latencyMs)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Section>
    </div>
  );
}
