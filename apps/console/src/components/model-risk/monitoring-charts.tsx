'use client';

import { Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';

import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import type { ModelMonitoring } from '@/lib/types/model-risk';

const passConfig = { passRate: { label: 'Eval pass rate', color: 'var(--chart-2)' } } satisfies ChartConfig;
const overrideConfig = { rate: { label: 'Override rate', color: 'var(--chart-4)' } } satisfies ChartConfig;
const percent = (v: number) => `${Math.round(v * 100)}%`;
const shortDay = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString('en-CA', { month: 'short', day: 'numeric' });

/** Eval pass rate per version: a drop on the newest bar is the signal to look before it is pinned. */
export function PassRateChart({ data }: { data: ModelMonitoring['passRateByVersion'] }) {
  if (!data.length) return <p className="py-10 text-center text-sm text-muted-foreground">No eval runs yet.</p>;
  return (
    <ChartContainer config={passConfig} className="aspect-auto h-48 w-full" data-testid="chart-pass-rate">
      <BarChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="version" tickLine={false} axisLine={false} tickMargin={8} fontSize={11} />
        <YAxis tickLine={false} axisLine={false} width={40} fontSize={11} domain={[0, 1]} tickFormatter={percent} />
        <ChartTooltip content={<ChartTooltipContent formatter={(v) => percent(Number(v))} />} />
        <Bar dataKey="passRate" fill="var(--color-passRate)" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ChartContainer>
  );
}

/** Share of reviewed actions where the approver changed or rejected the proposal, last 30 days. */
export function OverrideRateChart({ data }: { data: ModelMonitoring['overrideRate30d'] }) {
  return (
    <ChartContainer config={overrideConfig} className="aspect-auto h-48 w-full" data-testid="chart-override-rate">
      <LineChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="date" tickLine={false} axisLine={false} tickMargin={8} fontSize={11} tickFormatter={shortDay} minTickGap={24} />
        <YAxis tickLine={false} axisLine={false} width={40} fontSize={11} tickFormatter={percent} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(l) => shortDay(String(l))} formatter={(v) => percent(Number(v))} />} />
        <Line dataKey="rate" type="monotone" stroke="var(--color-rate)" strokeWidth={2} dot={false} />
      </LineChart>
    </ChartContainer>
  );
}
