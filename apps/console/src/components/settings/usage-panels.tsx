'use client';

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';

import { cad } from '@/components/logs/log-meta';
import { Section } from '@/components/shared/surface';
import { type ChartConfig, ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { Progress } from '@/components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { count } from '@/lib/format';
import type { UsageReport, UsageRow } from '@/lib/types/settings';

const COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)', 'var(--muted-foreground)'];

const compact = (n: number) => n.toLocaleString('en-CA', { notation: 'compact', maximumFractionDigits: 1 });
const shortDay = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString('en-CA', { month: 'short', day: 'numeric' });

/** Daily model cost, stacked by team (Platform) or by workflow (a team). */
export function UsageChart({ report }: { report: UsageReport }) {
  const config = Object.fromEntries(report.series.map((s, i) => [s.key, { label: s.label, color: COLORS[i % COLORS.length] }])) satisfies ChartConfig;
  return (
    <Section title={`Model cost per day · ${report.scope === 'all' ? 'by team' : 'by workflow'}`} description={`Last ${report.days} days, in CAD`}>
      <ChartContainer config={config} className="aspect-auto h-64 w-full">
        <BarChart data={report.daily} margin={{ left: 0, right: 8, top: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="date" tickLine={false} axisLine={false} tickMargin={8} fontSize={11} tickFormatter={shortDay} minTickGap={16} />
          <YAxis tickLine={false} axisLine={false} width={48} fontSize={11} tickFormatter={(v: number) => `$${compact(v)}`} />
          <ChartTooltip content={<ChartTooltipContent indicator="dot" labelFormatter={(l) => shortDay(String(l))} />} />
          <ChartLegend content={<ChartLegendContent />} />
          {report.series.map((s, i) => (
            <Bar key={s.key} dataKey={s.key} stackId="cost" fill={`var(--color-${s.key})`} radius={i === report.series.length - 1 ? [3, 3, 0, 0] : 0} />
          ))}
        </BarChart>
      </ChartContainer>
    </Section>
  );
}

/**
 * Chargeback table: runs, tool calls, tokens and model cost per row, with each row's share of cost.
 * The share bar is adapted from the shared component library's request attribution panel: a proportion of a whole, so Progress, not a quota meter.
 */
export function UsageTable({ title, description, rows, showTeam }: { title: string; description: string; rows: UsageRow[]; showTeam?: boolean }) {
  return (
    <Section title={title} description={description} flush>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-44">Name</TableHead>
              {showTeam && <TableHead>Team</TableHead>}
              <TableHead className="text-right">Runs</TableHead>
              <TableHead className="text-right">Tool calls</TableHead>
              <TableHead className="text-right">Tokens</TableHead>
              <TableHead className="text-right">Model cost</TableHead>
              <TableHead className="text-right">Per run</TableHead>
              <TableHead className="min-w-40">Share of cost</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.key}>
                <TableCell className="font-medium">{r.name}</TableCell>
                {showTeam && <TableCell className="whitespace-nowrap text-muted-foreground">{r.team}</TableCell>}
                <TableCell className="text-right tabular-nums">{count(r.runs)}</TableCell>
                <TableCell className="text-right tabular-nums">{count(r.toolCalls)}</TableCell>
                <TableCell className="text-right tabular-nums" title={count(r.tokens)}>
                  {compact(r.tokens)}
                </TableCell>
                <TableCell className="text-right font-medium tabular-nums">{cad(r.modelCost)}</TableCell>
                <TableCell className="text-right text-muted-foreground tabular-nums">{cad(r.costPerRun)}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Progress value={Math.round(r.share * 100)} className="w-24" aria-label={`${r.name} share of cost`} />
                    <span className="w-9 text-right text-xs text-muted-foreground tabular-nums">{Math.round(r.share * 100)}%</span>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Section>
  );
}
