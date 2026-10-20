'use client';

import Link from 'next/link';
import { Area, AreaChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';

import { Section, StatTile } from '@/components/shared/surface';
import { type ChartConfig, ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { count, ms } from '@/lib/format';
import type { ModuleActivity, ToolModule } from '@/lib/types/tool-modules';

import { ExecutionsTable } from './executions-table';
import { pctText } from './module-meta';

const shortDay = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString('en-CA', { month: 'short', day: 'numeric' });
const callsConfig = { ok: { label: 'Succeeded', color: 'var(--chart-1)' }, errors: { label: 'Failed', color: 'var(--destructive)' } } satisfies ChartConfig;
const latencyConfig = { p95Ms: { label: 'p95 latency', color: 'var(--chart-2)' } } satisfies ChartConfig;

/**
 * Calls over 14 days with failures stacked on top (the shape shows when failures started),
 * p95 latency, and the latest executions with their caller and a way into the full log.
 */
export function ActivityPanel({ module, activity, onOpenCall }: { module: ToolModule; activity: ModuleActivity; onOpenCall: (id: string) => void }) {
  // A day without calls has no latency: null leaves a gap in the p95 line instead of plotting 0 ms.
  const data = activity.days.map((d) => ({ date: d.date, ok: Math.max(0, d.count - d.errors), errors: d.errors, p95Ms: d.count ? d.p95Ms : null }));
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
              <Area dataKey="ok" type="monotone" fill="var(--color-ok)" stroke="var(--color-ok)" stackId="calls" fillOpacity={0.4} />
              <Area dataKey="errors" type="monotone" fill="var(--color-errors)" stroke="var(--color-errors)" stackId="calls" fillOpacity={0.4} />
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
              <Line dataKey="p95Ms" type="monotone" stroke="var(--color-p95Ms)" strokeWidth={2} dot />
            </LineChart>
          </ChartContainer>
        </Section>
      </div>
      <Section
        title="Executions"
        description="Who called which operation, how it was allowed, and what happened"
        actions={
          <Link href={`/logs/tool-calls?q=${encodeURIComponent(module.system)}`} className="text-sm font-medium underline-offset-4 hover:underline">
            Open in the tool call log
          </Link>
        }
        flush
      >
        <div className="p-4">
          <ExecutionsTable calls={activity.recent} onOpen={onOpenCall} />
        </div>
      </Section>
    </div>
  );
}
