'use client';

import { Activity, Bot, CheckCircle2, Layers } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';

import { EmptyState } from '@/components/shared/empty-state';
import { SettingsSection } from '@/components/shared/settings-section';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { Badge } from '@/components/ui/badge';
import { type ChartConfig, ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ms, pct, relativeTime } from '@/lib/format';
import type { SkillDetail, SkillTrace } from '@/lib/types/skills';

const COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)'];
const shortDay = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString('en-CA', { month: 'short', day: 'numeric' });
const key = (name: string) => name.replace(/[^a-zA-Z0-9]/g, '_');
const OUTCOME: Record<SkillTrace['outcome'], string> = { completed: 'Completed', handed_off: 'Handed to a person', failed: 'Failed' };

/** How often the runtime loads the skill, for which agents, and sample turns that loaded it. */
export function ActivityTab({ skill: s }: { skill: SkillDetail }) {
  const a = s.activity;
  if (!a.loadsPerDay.some((d) => d.total))
    return <EmptyState icon={Activity} title="Not loaded yet" description={s.usage.length ? 'Agents pin it, but no turn has loaded it in 14 days. Check the use-when line against what customers write.' : 'Attach it to an agent to see how often it loads.'} />;
  const config = Object.fromEntries(a.agents.map((n, i) => [key(n), { label: n, color: COLORS[i % COLORS.length] }])) satisfies ChartConfig;
  const data = a.loadsPerDay.map((d) => ({ date: d.date, ...Object.fromEntries(Object.entries(d.counts).map(([n, c]) => [key(n), c])) }));

  return (
    <div className="flex flex-col gap-4" data-testid="skill-activity-tab">
      <StatCardGrid columns={3}>
        <StatCard label="Loads · 30 days" value={a.loads30d.toLocaleString('en-CA')} icon={Layers} footer={{ text: `${a.loadsPerDay.reduce((n, d) => n + d.total, 0).toLocaleString('en-CA')} in 14 days`, subtext: 'Turns that loaded the skill' }} />
        <StatCard label="Success rate" value={a.successRate === null ? '—' : pct(a.successRate)} icon={CheckCircle2} footer={{ text: 'Completed without a hand-off', subtext: 'Of turns that loaded it' }} />
        <StatCard label="Agents" value={a.agents.length} icon={Bot} footer={{ text: a.agents.join(', '), subtext: 'Pinning a version' }} />
      </StatCardGrid>
      <SettingsSection title="Loads per day by agent" description="Last 14 days.">
        <ChartContainer config={config} className="aspect-auto h-56 w-full" data-testid="chart-skill-loads">
          <BarChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="date" tickLine={false} axisLine={false} tickMargin={8} fontSize={11} tickFormatter={shortDay} minTickGap={16} />
            <YAxis tickLine={false} axisLine={false} width={32} fontSize={11} allowDecimals={false} />
            <ChartTooltip content={<ChartTooltipContent labelFormatter={(l) => shortDay(String(l))} />} />
            <ChartLegend content={<ChartLegendContent />} />
            {a.agents.map((n, i) => (
              <Bar key={n} dataKey={key(n)} stackId="loads" fill={`var(--color-${key(n)})`} radius={i === a.agents.length - 1 ? [3, 3, 0, 0] : 0} />
            ))}
          </BarChart>
        </ChartContainer>
      </SettingsSection>
      <SettingsSection title="Sample turns" description="Recent turns that loaded the skill, from the run journal.">
        <div className="overflow-x-auto rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Message</TableHead>
                <TableHead>Tools called</TableHead>
                <TableHead>Outcome</TableHead>
                <TableHead className="text-right">Took</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {a.samples.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="text-xs whitespace-nowrap text-muted-foreground">{relativeTime(t.at)}</TableCell>
                  <TableCell className="text-xs whitespace-nowrap">
                    {t.agentName} <span className="font-mono text-muted-foreground">v{t.version}</span>
                  </TableCell>
                  <TableCell className="max-w-80 truncate text-xs" title={t.input}>
                    {t.input}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {t.toolCalls.length ? (
                        t.toolCalls.map((c) => (
                          <Badge key={c} variant="secondary" className="font-mono text-[10px] font-normal">
                            {c}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-xs text-muted-foreground">None</span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs whitespace-nowrap">{OUTCOME[t.outcome]}</TableCell>
                  <TableCell className="text-right text-xs tabular-nums">{ms(t.tookMs)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </SettingsSection>
    </div>
  );
}
