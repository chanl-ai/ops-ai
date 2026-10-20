'use client';

// The one renderer set for chat widgets (c-176): every generic kind, every shaped tool result (converted to a kind in
// lib/widgets/kinds.ts) and every kind placed in a template or composed layout draws here. Composed from AI Elements,
// shadcn chart and shadcn components on the console's tokens; the industry is only ever in the data.

import * as React from 'react';
import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { ArrowDownRight, ArrowUpRight, BookOpen, CalendarClock, Check, CircleDashed, CircleX, Copy, ExternalLink, FileText, Loader2, Mail, MapPin, Phone, Search, Star } from 'lucide-react';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, LabelList, Line, LineChart, XAxis, YAxis } from 'recharts';

import { Artifact, ArtifactAction, ArtifactActions, ArtifactContent, ArtifactDescription, ArtifactHeader, ArtifactTitle } from '@/components/ai-elements/artifact';
import { ChainOfThought, ChainOfThoughtContent, ChainOfThoughtHeader, ChainOfThoughtSearchResult, ChainOfThoughtSearchResults, ChainOfThoughtStep } from '@/components/ai-elements/chain-of-thought';
import { Plan, PlanContent, PlanDescription, PlanFooter, PlanHeader, PlanTitle, PlanTrigger } from '@/components/ai-elements/plan';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { type ChartConfig, ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { DocumentReadSection, type ReadChecks, type ReadEdits } from '@/components/reviews/document-read';
import { DocumentViewer } from '@/components/shared/document-viewer';
import { useFilePreviewUrl } from '@/hooks/extraction-queries';
import { money } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { Cell, ChartNode, ColumnFormat, KindAction, KindNode, KindStatus, MetricNode, Rows, StepStateKind, TableNode, Tone } from '@/lib/types/widgets';

/** What the thread lets a widget do. Undefined when the conversation is read-only. */
export interface KindActions {
  /** Sends a button's, slot's or form's message back to the agent as the person's next message. */
  onReply?: (text: string) => void;
  /** A shaped form (a tool's form) submits its values to that tool instead of sending a message. */
  onSubmit?: (values: Record<string, Cell>) => Promise<unknown>;
  /** A shaped decision (a held write) is decided on its review instead of sending a message. */
  onAnswer?: (approved: boolean) => Promise<unknown>;
}

const TONE_BADGE: Record<Tone, string> = {
  neutral: '',
  info: 'border-primary/30 bg-primary/10 text-primary',
  success: 'border-success/30 bg-success/10 text-success-text',
  warning: 'border-warning/30 bg-warning/10 text-warning-text',
  danger: 'border-destructive/30 bg-destructive/10 text-destructive',
};
const TONE_DOT: Record<Tone, string> = { neutral: 'bg-muted-foreground', info: 'bg-primary', success: 'bg-success', warning: 'bg-warning', danger: 'bg-destructive' };
const COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-4)', 'var(--chart-3)', 'var(--chart-5)'];
/** Every kind arrives the same way; off when the person asks for reduced motion. */
const ENTER = 'animate-in fade-in-0 slide-in-from-bottom-1 duration-300 motion-reduce:animate-none';

export const cellText = (v: Cell | undefined) => (v === null || v === undefined ? '—' : typeof v === 'boolean' ? (v ? 'Yes' : 'No') : typeof v === 'number' ? v.toLocaleString() : v);

function formatted(v: Cell, format?: ColumnFormat): string {
  if (typeof v !== 'number') return cellText(v);
  if (format === 'money') return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (format === 'percent') return `${v.toLocaleString()}%`;
  return v.toLocaleString();
}

const amount = (n: number, currency: string) => money(n, currency);

function StatusBadge({ status }: { status?: KindStatus }) {
  return status ? (
    <Badge variant="outline" className={TONE_BADGE[status.tone ?? 'neutral']}>
      {status.text}
    </Badge>
  ) : null;
}

function ActionButtons({ actions, onReply, primaryLast = true }: { actions?: KindAction[]; onReply?: (t: string) => void; primaryLast?: boolean }) {
  if (!actions?.length) return null;
  return (
    <div className="flex flex-wrap justify-end gap-2">
      {actions.map((a, i) => (
        <Button key={a.label} size="sm" variant={primaryLast && i === actions.length - 1 ? 'default' : 'outline'} disabled={!onReply} onClick={() => onReply?.(a.reply)} title={onReply ? `Sends: ${a.reply}` : undefined}>
          {a.label}
        </Button>
      ))}
    </div>
  );
}

function StepIcon({ state }: { state: StepStateKind | 'done' | 'active' | 'pending' }) {
  if (state === 'done') return <Check className="size-4 shrink-0 text-success-text" aria-label="Done" />;
  if (state === 'active') return <Loader2 className="size-4 shrink-0 animate-spin text-primary motion-reduce:animate-none" aria-label="In progress" />;
  if (state === 'failed') return <CircleX className="size-4 shrink-0 text-destructive" aria-label="Failed" />;
  return <CircleDashed className="size-4 shrink-0 text-muted-foreground" aria-label="Not started" />;
}

// ── figures and data ──

function MetricKind({ node }: { node: MetricNode }) {
  const delta = node.delta ?? 0;
  const good = node.goodWhen ? (node.goodWhen === 'up' ? delta > 0 : delta < 0) : undefined;
  const config = { v: { label: node.label, color: 'var(--chart-1)' } } satisfies ChartConfig;
  return (
    <Card className={cn(ENTER, 'gap-2')} data-kind="metric">
      <CardHeader>
        <CardDescription>{node.label}</CardDescription>
        <CardTitle className="text-3xl tabular-nums">
          {typeof node.value === 'number' ? node.value.toLocaleString() : node.value}
          {node.unit && <span className="ml-1 text-base font-normal text-muted-foreground">{node.unit}</span>}
        </CardTitle>
        {delta !== 0 && (
          <CardAction>
            <Badge variant="outline" className={good === undefined ? '' : good ? 'text-success-text' : 'text-destructive'}>
              {delta > 0 ? <ArrowUpRight /> : <ArrowDownRight />}
              {delta > 0 ? '+' : ''}
              {delta.toLocaleString()}
              {node.deltaLabel ? ` ${node.deltaLabel}` : ''}
            </Badge>
          </CardAction>
        )}
      </CardHeader>
      {node.trend && (
        <CardContent>
          <ChartContainer config={config} className="aspect-auto h-10 w-full">
            <AreaChart data={node.trend.map((v, i) => ({ i, v }))} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
              <Area dataKey="v" type="monotone" fill="var(--color-v)" fillOpacity={0.15} stroke="var(--color-v)" strokeWidth={1.5} />
            </AreaChart>
          </ChartContainer>
        </CardContent>
      )}
    </Card>
  );
}

/** Rows on the console's data table, sortable and paged (10 a page); columns named and formatted when given. */
function TableKind({ node, truncatedFrom }: { node: TableNode; truncatedFrom?: number }) {
  const cols = React.useMemo(() => node.columns ?? Object.keys(node.rows[0] ?? {}).map((key) => ({ key, label: key, format: undefined as ColumnFormat | undefined })), [node]);
  const columns = React.useMemo<ColumnDef<Rows[number]>[]>(
    () =>
      cols.map((c) => ({
        // Keys can hold dots, which an accessorKey would read as a path.
        id: c.key,
        accessorFn: (r) => r[c.key],
        header: ({ column }) => <DataTableColumnHeader column={column} title={c.label ?? c.key} />,
        cell: ({ row }) => {
          const v = row.original[c.key] ?? null;
          return <span className={typeof v === 'number' ? 'block text-right text-xs tabular-nums' : 'text-xs whitespace-nowrap'}>{formatted(v, c.format)}</span>;
        },
      })),
    [cols],
  );
  return (
    <div className="p-2" data-kind="table" data-testid="widget-table">
      <DataTableWithViews columns={columns} data={node.rows} hideViewSwitcher />
      {truncatedFrom && truncatedFrom > node.rows.length && (
        <p className="px-2 pt-1 text-xs text-muted-foreground" data-testid="widget-truncated">
          Showing {node.rows.length.toLocaleString()} of {truncatedFrom.toLocaleString()} rows
        </p>
      )}
    </div>
  );
}

function ChartKind({ node }: { node: ChartNode }) {
  const kind = node.kind ?? 'line';
  // Series keys can hold spaces, so each is drawn as s0, s1, … and labelled with its name.
  const keys = node.y.map((_, i) => `s${i}`);
  const config = Object.fromEntries(node.y.map((name, i) => [`s${i}`, { label: name, color: COLORS[i % COLORS.length] }])) satisfies ChartConfig;
  const rows = node.rows.map((r) => Object.fromEntries([['x', r[node.x]], ...node.y.map((name, i) => [`s${i}`, r[name]])]));
  const label = `${kind[0].toUpperCase()}${kind.slice(1)} chart of ${node.y.join(' and ')} by ${node.x}`;
  const grid = (
    <>
      <CartesianGrid vertical={false} />
      <XAxis dataKey="x" tickLine={false} axisLine={false} tickMargin={8} fontSize={11} interval="preserveStartEnd" />
      <YAxis tickLine={false} axisLine={false} width={44} fontSize={11} />
      <ChartTooltip cursor={false} content={<ChartTooltipContent indicator={kind === 'bar' ? 'dot' : 'line'} />} />
      {keys.length > 1 && <ChartLegend content={<ChartLegendContent />} />}
    </>
  );
  return (
    <ChartContainer config={config} className={cn(ENTER, 'aspect-auto h-56 w-full p-3')} role="img" aria-label={label} data-kind="chart" data-testid={`widget-${kind}`}>
      {kind === 'bar' ? (
        <BarChart data={rows} margin={{ left: 0, right: 8, top: 16 }}>
          {grid}
          {keys.map((k) => (
            <Bar key={k} dataKey={k} fill={`var(--color-${k})`} radius={4}>
              {keys.length === 1 && <LabelList dataKey={k} position="top" className="fill-foreground" fontSize={11} />}
            </Bar>
          ))}
        </BarChart>
      ) : kind === 'area' ? (
        <AreaChart data={rows} margin={{ left: 0, right: 8, top: 8 }}>
          {grid}
          {keys.map((k) => (
            <Area key={k} dataKey={k} type="natural" stroke={`var(--color-${k})`} fill={`var(--color-${k})`} fillOpacity={0.25} />
          ))}
        </AreaChart>
      ) : (
        <LineChart data={rows} margin={{ left: 0, right: 8, top: 8 }}>
          {grid}
          {keys.map((k) => (
            <Line key={k} dataKey={k} type="monotone" stroke={`var(--color-${k})`} strokeWidth={2} dot={false} />
          ))}
        </LineChart>
      )}
    </ChartContainer>
  );
}

// ── processes and activity ──

function TimelineKind({ node }: { node: Extract<KindNode, { type: 'timeline' }> }) {
  return (
    <Card className={ENTER} data-kind="timeline">
      {node.title && (
        <CardHeader>
          <CardTitle>{node.title}</CardTitle>
        </CardHeader>
      )}
      <CardContent>
        <ol className="relative flex flex-col gap-4 border-l pl-5">
          {node.events.map((e, i) => (
            <li key={i} className="relative">
              <span className={cn('absolute top-1.5 -left-[25px] size-2.5 rounded-full ring-4 ring-card', TONE_DOT[e.tone ?? 'neutral'])} aria-hidden />
              <p className="text-xs text-muted-foreground tabular-nums">{e.at}</p>
              <p className="text-sm font-medium">{e.title}</p>
              {e.detail && <p className="text-sm text-muted-foreground">{e.detail}</p>}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function TrackerKind({ node }: { node: Extract<KindNode, { type: 'tracker' }> }) {
  const done = node.steps.filter((s) => s.state === 'done').length;
  const current = node.steps.find((s) => s.state === 'active' || s.state === 'failed');
  return (
    <Card className={ENTER} data-kind="tracker">
      <CardHeader>
        <CardTitle>{node.title ?? 'Progress'}</CardTitle>
        <CardDescription>
          {node.reference ? `${node.reference} · ` : ''}
          {done} of {node.steps.length} done{current ? ` · ${current.label}` : ''}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Progress value={(done / node.steps.length) * 100} aria-label={`${done} of ${node.steps.length} steps done`} />
        <ol className="flex flex-col gap-3">
          {node.steps.map((s, i) => (
            <li key={i} className="flex gap-3">
              <StepIcon state={s.state} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                  <span className={cn('text-sm', s.state === 'pending' ? 'text-muted-foreground' : 'font-medium')}>{s.label}</span>
                  {s.at && <span className="text-xs text-muted-foreground tabular-nums">{s.at}</span>}
                </div>
                {s.detail && <p className="text-xs text-muted-foreground">{s.detail}</p>}
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function ChecklistKind({ node }: { node: Extract<KindNode, { type: 'checklist' }> }) {
  const done = node.items.filter((i) => i.done).length;
  return (
    <Card className={ENTER} data-kind="checklist">
      <CardHeader>
        <CardTitle>{node.title ?? 'Checklist'}</CardTitle>
        <CardDescription>
          {done} of {node.items.length} done
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-3">
          {node.items.map((it, i) => (
            <li key={i} className="flex items-start gap-3">
              <Checkbox checked={it.done} disabled aria-label={it.label} className="mt-0.5" />
              <div>
                <p className={cn('text-sm', it.done && 'text-muted-foreground line-through')}>{it.label}</p>
                {it.detail && <p className="text-xs text-muted-foreground">{it.detail}</p>}
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function PlanKind({ node, onReply }: { node: Extract<KindNode, { type: 'plan' }>; onReply?: (t: string) => void }) {
  return (
    <Plan defaultOpen className={ENTER} data-kind="plan">
      <PlanHeader>
        <div>
          <PlanTitle>{node.title}</PlanTitle>
          {node.description && <PlanDescription>{node.description}</PlanDescription>}
        </div>
        <PlanTrigger />
      </PlanHeader>
      <PlanContent>
        <ol className="flex flex-col gap-2 text-sm">
          {node.steps.map((s, i) => (
            <li key={i} className="flex items-start gap-2">
              <StepIcon state={s.state} />
              <span className={s.state === 'pending' ? 'text-muted-foreground' : ''}>
                {s.label}
                {s.detail && <span className="block text-xs text-muted-foreground">{s.detail}</span>}
              </span>
            </li>
          ))}
        </ol>
      </PlanContent>
      {node.action && (
        <PlanFooter className="justify-end">
          <ActionButtons actions={[node.action]} onReply={onReply} />
        </PlanFooter>
      )}
    </Plan>
  );
}

function ReasoningKind({ node }: { node: Extract<KindNode, { type: 'reasoning' }> }) {
  const status = { done: 'complete', active: 'active', pending: 'pending' } as const;
  return (
    <ChainOfThought defaultOpen className={ENTER} data-kind="reasoning">
      <ChainOfThoughtHeader>{node.title ?? 'How the agent worked this out'}</ChainOfThoughtHeader>
      <ChainOfThoughtContent>
        {node.steps.map((s, i) => (
          <ChainOfThoughtStep key={i} label={s.label} description={s.detail} status={status[s.state]} icon={s.results?.length ? Search : undefined}>
            {!!s.results?.length && (
              <ChainOfThoughtSearchResults>
                {s.results.map((r) => (
                  <ChainOfThoughtSearchResult key={r}>{r}</ChainOfThoughtSearchResult>
                ))}
              </ChainOfThoughtSearchResults>
            )}
          </ChainOfThoughtStep>
        ))}
      </ChainOfThoughtContent>
    </ChainOfThought>
  );
}

// ── things and people ──

const initialsOf = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('');

function EntityKind({ node, onReply }: { node: Extract<KindNode, { type: 'entity' }>; onReply?: (t: string) => void }) {
  return (
    <Card className={ENTER} data-kind="entity">
      <CardHeader className="flex flex-row items-center gap-3">
        <Avatar className="size-10">
          <AvatarFallback>{initialsOf(node.title)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0 flex-1">
          {node.category && <p className="text-xs text-muted-foreground">{node.category}</p>}
          <CardTitle className="truncate">{node.title}</CardTitle>
          {node.subtitle && <CardDescription className="truncate">{node.subtitle}</CardDescription>}
        </div>
        <StatusBadge status={node.status} />
      </CardHeader>
      {node.fields.length > 0 && (
        <CardContent>
          <dl className="grid grid-cols-[minmax(0,9rem)_1fr] gap-x-4 gap-y-2 text-sm">
            {node.fields.map((f, i) => (
              <React.Fragment key={i}>
                <dt className="text-muted-foreground">{f.label}</dt>
                <dd className="min-w-0 font-medium break-words tabular-nums">
                  {f.href ? (
                    <Link href={f.href} className="underline underline-offset-2">
                      {cellText(f.value)}
                    </Link>
                  ) : (
                    cellText(f.value)
                  )}
                </dd>
              </React.Fragment>
            ))}
          </dl>
        </CardContent>
      )}
      {!!node.actions?.length && (
        <CardFooter className="justify-end">
          <ActionButtons actions={node.actions} onReply={onReply} />
        </CardFooter>
      )}
    </Card>
  );
}

function CopyLine({ icon: Icon, text }: { icon: typeof Phone; text: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <div className="flex items-center gap-2 text-sm">
      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="min-w-0 flex-1 truncate">{text}</span>
      <Button
        size="icon"
        variant="ghost"
        className="size-7"
        aria-label={`Copy ${text}`}
        onClick={() => navigator.clipboard?.writeText(text).then(() => (setCopied(true), setTimeout(() => setCopied(false), 1500)), () => undefined)}
      >
        {copied ? <Check /> : <Copy />}
      </Button>
    </div>
  );
}

function ContactKind({ node, onReply }: { node: Extract<KindNode, { type: 'contact' }>; onReply?: (t: string) => void }) {
  return (
    <Card className={ENTER} data-kind="contact">
      <CardHeader className="flex flex-row items-center gap-3">
        <Avatar className="size-10">
          <AvatarFallback>{initialsOf(node.name)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <CardTitle className="truncate">{node.name}</CardTitle>
          {(node.role || node.organisation) && <CardDescription className="truncate">{[node.role, node.organisation].filter(Boolean).join(' · ')}</CardDescription>}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        {/* Shown as text to copy: a kind carries no link (ops_agent_kernel.kinds). */}
        {node.phone && <CopyLine icon={Phone} text={node.phone} />}
        {node.email && <CopyLine icon={Mail} text={node.email} />}
        {node.address && <CopyLine icon={MapPin} text={node.address} />}
        {node.hours && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <CalendarClock className="size-4" aria-hidden /> {node.hours}
          </p>
        )}
      </CardContent>
      {!!node.actions?.length && (
        <CardFooter className="justify-end">
          <ActionButtons actions={node.actions} onReply={onReply} />
        </CardFooter>
      )}
    </Card>
  );
}

function ComparisonKind({ node, onReply }: { node: Extract<KindNode, { type: 'comparison' }>; onReply?: (t: string) => void }) {
  return (
    <Card className={ENTER} data-kind="comparison">
      {node.title && (
        <CardHeader>
          <CardTitle>{node.title}</CardTitle>
        </CardHeader>
      )}
      <CardContent className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-36" />
              {node.options.map((o) => (
                <TableHead key={o.name} className={cn('min-w-32 align-bottom', o.recommended && 'bg-primary/5')}>
                  <span className="flex flex-col gap-1 py-1">
                    {o.badge && (
                      <Badge variant={o.recommended ? 'default' : 'secondary'} className="w-fit">
                        {o.recommended && <Star />}
                        {o.badge}
                      </Badge>
                    )}
                    <span className="font-semibold text-foreground">{o.name}</span>
                  </span>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {node.attributes.map((a) => (
              <TableRow key={a}>
                <TableCell className="text-muted-foreground">{a}</TableCell>
                {node.options.map((o) => (
                  <TableCell key={o.name} className={cn('tabular-nums', o.recommended && 'bg-primary/5 font-medium')}>
                    {cellText(o.values[a])}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
          {node.options.some((o) => o.action) && (
            <TableFooter className="bg-transparent">
              <TableRow>
                <TableCell />
                {node.options.map((o) => (
                  <TableCell key={o.name}>
                    {o.action && (
                      <Button size="sm" variant={o.recommended ? 'default' : 'outline'} className="h-auto w-full py-1.5 whitespace-normal" disabled={!onReply} onClick={() => onReply?.(o.action!.reply)}>
                        {o.action.label}
                      </Button>
                    )}
                  </TableCell>
                ))}
              </TableRow>
            </TableFooter>
          )}
        </Table>
      </CardContent>
    </Card>
  );
}

function ReceiptKind({ node }: { node: Extract<KindNode, { type: 'receipt' }> }) {
  return (
    <Card className={ENTER} data-kind="receipt">
      <CardHeader>
        <CardTitle>{node.title}</CardTitle>
        <CardDescription>{[node.number, node.date, node.party].filter(Boolean).join(' · ')}</CardDescription>
        {node.status && (
          <CardAction>
            <StatusBadge status={node.status} />
          </CardAction>
        )}
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {node.lines.map((l, i) => (
              <TableRow key={i}>
                <TableCell className="whitespace-normal">
                  {l.label}
                  {l.unitPrice !== undefined && <span className="block text-xs text-muted-foreground">{amount(l.unitPrice, node.currency)} each</span>}
                </TableCell>
                <TableCell className="text-right tabular-nums">{l.quantity ?? ''}</TableCell>
                <TableCell className="text-right tabular-nums">{amount(l.amount, node.currency)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <dl className="mt-3 ml-auto grid w-full max-w-64 grid-cols-2 gap-y-1 text-sm tabular-nums">
          {node.subtotal !== undefined && (
            <>
              <dt className="text-muted-foreground">Subtotal</dt>
              <dd className="text-right">{amount(node.subtotal, node.currency)}</dd>
            </>
          )}
          {node.tax !== undefined && (
            <>
              <dt className="text-muted-foreground">Tax</dt>
              <dd className="text-right">{amount(node.tax, node.currency)}</dd>
            </>
          )}
          <dt className="border-t pt-1 font-semibold">Total</dt>
          <dd className="border-t pt-1 text-right font-semibold">{amount(node.total, node.currency)}</dd>
        </dl>
      </CardContent>
    </Card>
  );
}

// ── sources ──

function DocumentKind({ node, onOpenFile }: { node: Extract<KindNode, { type: 'document' }>; onOpenFile?: (fileId: string, page?: number) => void }) {
  return (
    <Artifact className={ENTER} data-kind="document">
      <ArtifactHeader>
        <div className="min-w-0">
          <ArtifactTitle className="flex items-center gap-2">
            <FileText className="size-4 shrink-0" aria-hidden /> <span className="truncate">{node.name}</span>
          </ArtifactTitle>
          {node.page && (
            <ArtifactDescription>
              Page {node.page}
              {node.pages ? ` of ${node.pages}` : ''}
            </ArtifactDescription>
          )}
        </div>
        {node.fileId && onOpenFile && (
          <ArtifactActions>
            <ArtifactAction tooltip="Open the file at this page" label="Open" icon={ExternalLink} onClick={() => onOpenFile(node.fileId!, node.page)} />
          </ArtifactActions>
        )}
      </ArtifactHeader>
      <ArtifactContent>
        <div className="rounded-md border bg-background p-4 font-serif text-sm leading-relaxed shadow-xs">
          {node.before}
          <mark className="rounded-sm bg-warning/25 px-0.5 text-foreground">{node.passage}</mark>
          {node.after}
        </div>
      </ArtifactContent>
    </Artifact>
  );
}

function QuoteKind({ node, onOpenFile }: { node: Extract<KindNode, { type: 'quote' }>; onOpenFile?: (fileId: string, page?: number) => void }) {
  const pct = node.confidence !== undefined ? Math.round(node.confidence * 100) : undefined;
  return (
    <Card className={ENTER} data-kind="quote">
      <CardHeader>
        <CardDescription className="flex items-center gap-2">
          <BookOpen className="size-4" aria-hidden /> {node.source}
          {node.page ? ` · page ${node.page}` : ''}
        </CardDescription>
        {pct !== undefined && (
          <CardAction>
            <Badge variant="outline" className="tabular-nums">
              {pct}% match
            </Badge>
          </CardAction>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <blockquote className="border-l-2 border-primary pl-3 text-sm leading-relaxed">{node.passage}</blockquote>
        {pct !== undefined && <Progress value={pct} aria-label="How closely the passage matches" />}
      </CardContent>
      {node.fileId && onOpenFile && (
        <CardFooter className="justify-end">
          <Button size="sm" variant="ghost" onClick={() => onOpenFile(node.fileId!, node.page)}>
            Open source <ExternalLink />
          </Button>
        </CardFooter>
      )}
    </Card>
  );
}

// ── asking the person ──

function FormKind({ node, actions }: { node: Extract<KindNode, { type: 'form' }>; actions: KindActions }) {
  const [values, setValues] = React.useState<Record<string, Cell>>(() => Object.fromEntries(node.fields.map((f) => [f.name, f.type === 'boolean' ? false : ''])));
  const [state, setState] = React.useState<'open' | 'sending' | 'sent'>('open');
  const send = actions.onSubmit ?? (actions.onReply && ((v: Record<string, Cell>) => (actions.onReply!(answerText(node, v)), Promise.resolve())));
  const missing = node.fields.some((f) => f.required && (values[f.name] === '' || values[f.name] === null));
  const set = (k: string, v: Cell) => setValues((x) => ({ ...x, [k]: v }));
  const disabled = !send || state !== 'open';
  return (
    <Card className={ENTER} data-kind="form">
      {node.title && (
        <CardHeader>
          <CardTitle>{node.title}</CardTitle>
        </CardHeader>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!send) return;
          setState('sending');
          send(values).then(() => setState('sent'), () => setState('open'));
        }}
      >
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {node.fields.map((f) => {
            const id = `wk-${f.name}`;
            if (f.type === 'boolean')
              return (
                <label key={f.name} className="flex items-center gap-2 text-sm sm:col-span-2">
                  <Switch id={id} checked={values[f.name] === true} disabled={disabled} onCheckedChange={(v) => set(f.name, v)} /> {f.label}
                </label>
              );
            return (
              <div key={f.name} className={cn('grid gap-1.5', f.type === 'textarea' && 'sm:col-span-2')}>
                <Label htmlFor={id}>
                  {f.label}
                  {f.required ? '' : <span className="font-normal text-muted-foreground"> (optional)</span>}
                </Label>
                {f.type === 'select' ? (
                  <Select value={String(values[f.name] ?? '')} disabled={disabled} onValueChange={(v) => set(f.name, v)}>
                    <SelectTrigger id={id} className="w-full">
                      <SelectValue placeholder={f.placeholder ?? 'Choose'} />
                    </SelectTrigger>
                    <SelectContent>
                      {(f.options ?? []).map((o) => (
                        <SelectItem key={o} value={o}>
                          {o}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : f.type === 'textarea' ? (
                  <Textarea id={id} rows={3} placeholder={f.placeholder} value={String(values[f.name] ?? '')} disabled={disabled} onChange={(e) => set(f.name, e.target.value)} />
                ) : (
                  <Input
                    id={id}
                    type={f.type === 'date' ? 'date' : 'text'}
                    inputMode={f.type === 'number' ? 'decimal' : undefined}
                    placeholder={f.placeholder}
                    value={String(values[f.name] ?? '')}
                    disabled={disabled}
                    onChange={(e) => set(f.name, f.type === 'number' && e.target.value !== '' ? Number(e.target.value) : e.target.value)}
                  />
                )}
              </div>
            );
          })}
        </CardContent>
        <CardFooter className="mt-4 justify-end">
          <Button type="submit" size="sm" disabled={!send || missing || state !== 'open'}>
            {state === 'sending' ? <Loader2 className="animate-spin" /> : null}
            {state === 'sent' ? 'Sent' : node.submit.label}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}

/** A form's answers as the message the agent reads: its reply, then each filled field by label. */
export function answerText(node: Extract<KindNode, { type: 'form' }>, values: Record<string, Cell>): string {
  const filled = node.fields.filter((f) => values[f.name] !== '' && values[f.name] !== null && values[f.name] !== undefined).map((f) => `${f.label}: ${cellText(values[f.name])}`);
  return filled.length ? `${node.submit.reply} (${filled.join(', ')})` : node.submit.reply;
}

function ConfirmKind({ node, actions }: { node: Extract<KindNode, { type: 'confirm' }>; actions: KindActions }) {
  const [answered, setAnswered] = React.useState<'confirmed' | 'cancelled'>();
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string>();
  const answer = (yes: boolean) => {
    const a = yes ? node.confirm : node.cancel;
    setError(undefined);
    if (actions.onAnswer) {
      setBusy(true);
      actions
        .onAnswer(yes)
        .then(
          () => setAnswered(yes ? 'confirmed' : 'cancelled'),
          (e: unknown) => setError(e instanceof Error ? e.message : 'The answer was not saved. Try again.'),
        )
        .finally(() => setBusy(false));
      return;
    }
    if (a && actions.onReply) {
      actions.onReply(a.reply);
      setAnswered(yes ? 'confirmed' : 'cancelled');
    }
  };
  const can = !!(actions.onAnswer || actions.onReply) && !answered;
  return (
    <Card className={cn(ENTER, node.tone === 'warning' && 'border-warning/40', node.tone === 'danger' && 'border-destructive/40')} data-kind="confirm">
      <CardHeader>
        <CardTitle>{node.title}</CardTitle>
        {node.summary && <CardDescription>{node.summary}</CardDescription>}
        {answered && (
          <CardAction>
            <Badge variant="outline" className={answered === 'confirmed' ? 'text-success-text' : ''}>
              {answered === 'confirmed' ? node.confirm.label : (node.cancel?.label ?? 'Cancelled')}
            </Badge>
          </CardAction>
        )}
      </CardHeader>
      {!!node.details?.length && (
        <CardContent>
          <dl className="grid grid-cols-[minmax(0,9rem)_1fr] gap-x-4 gap-y-1.5 rounded-md bg-muted/50 p-3 text-sm">
            {node.details.map((d, i) => (
              <React.Fragment key={i}>
                <dt className="text-muted-foreground">{d.label}</dt>
                <dd className="font-medium break-words tabular-nums">{cellText(d.value)}</dd>
              </React.Fragment>
            ))}
          </dl>
        </CardContent>
      )}
      {!node.actionsOff && (
      <CardFooter className="justify-end gap-2">
        {error && (
          <p className="mr-auto text-xs text-destructive" role="alert">
            {error}
          </p>
        )}
        {node.cancel && (
          <Button size="sm" variant="outline" disabled={!can || busy} onClick={() => answer(false)}>
            {node.cancel.label}
          </Button>
        )}
        <Button size="sm" disabled={!can || busy} onClick={() => answer(true)}>
          {busy ? <Loader2 className="animate-spin" /> : null}
          {node.confirm.label}
        </Button>
      </CardFooter>
      )}
    </Card>
  );
}

function SlotsKind({ node, onReply }: { node: Extract<KindNode, { type: 'slots' }>; onReply?: (t: string) => void }) {
  const [picked, setPicked] = React.useState<string>();
  return (
    <Card className={ENTER} data-kind="slots">
      <CardHeader>
        <CardTitle>{node.title}</CardTitle>
        {node.timezone && <CardDescription>Times in {node.timezone}</CardDescription>}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {node.days.map((d) => (
          <div key={d.day} className="flex flex-col gap-2">
            <p className="text-sm font-medium">{d.day}</p>
            <div className="flex flex-wrap gap-2" role="group" aria-label={d.day}>
              {d.slots.map((s) => {
                const key = `${d.day} ${s.label}`;
                return (
                  <Button
                    key={s.label}
                    size="sm"
                    variant={picked === key ? 'default' : 'outline'}
                    className="tabular-nums"
                    disabled={!s.available || !onReply || !!picked}
                    aria-label={s.available ? `${d.day} ${s.label}` : `${d.day} ${s.label}, taken`}
                    onClick={() => {
                      setPicked(key);
                      onReply?.(`${node.reply} ${key}`);
                    }}
                  >
                    {s.label}
                  </Button>
                );
              })}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export interface KindViewProps {
  node: MetricNode | TableNode | ChartNode | KindNode;
  actions?: KindActions;
  /** Opens a cited file in the console's Files panel; absent where there is none, and Open is then not shown. */
  onOpenFile?: (fileId: string, page?: number) => void;
  /** Table only: how many rows the result had before agents-service cut it. */
  truncatedFrom?: number;
  /** field_check only: the person's typed corrections, and whether the values are open for editing. */
  fieldEdits?: { open: boolean; edits: ReadEdits; onEdit: (record: number, key: string, text: string) => void; checks?: ReadChecks };
}

/** Draws one kind node. */
export function KindView({ node, actions = {}, onOpenFile, truncatedFrom, fieldEdits }: KindViewProps) {
  const reply = actions.onReply;
  switch (node.type) {
    case 'metric':
      return <MetricKind node={node} />;
    case 'table':
      return <TableKind node={node} truncatedFrom={truncatedFrom} />;
    case 'chart':
      return <ChartKind node={node} />;
    case 'timeline':
      return <TimelineKind node={node} />;
    case 'tracker':
      return <TrackerKind node={node} />;
    case 'entity':
      return <EntityKind node={node} onReply={reply} />;
    case 'comparison':
      return <ComparisonKind node={node} onReply={reply} />;
    case 'checklist':
      return <ChecklistKind node={node} />;
    case 'form':
      return <FormKind node={node} actions={actions} />;
    case 'confirm':
      return <ConfirmKind node={node} actions={actions} />;
    case 'document':
      return <DocumentKind node={node} onOpenFile={onOpenFile} />;
    case 'quote':
      return <QuoteKind node={node} onOpenFile={onOpenFile} />;
    case 'plan':
      return <PlanKind node={node} onReply={reply} />;
    case 'reasoning':
      return <ReasoningKind node={node} />;
    case 'slots':
      return <SlotsKind node={node} onReply={reply} />;
    case 'receipt':
      return <ReceiptKind node={node} />;
    case 'contact':
      return <ContactKind node={node} onReply={reply} />;
    case 'viewer':
      return <ViewerKind node={node} />;
    case 'field_check':
      return (
        <DocumentReadSection
          read={node.read}
          open={fieldEdits?.open ?? false}
          edits={fieldEdits?.edits ?? NO_EDITS}
          onEdit={fieldEdits?.onEdit ?? IGNORE_EDIT}
          confirmed={fieldEdits?.checks?.confirmed}
          onConfirm={fieldEdits?.checks?.onConfirm}
        />
      );
  }
}

const NO_EDITS: ReadEdits = {};
const IGNORE_EDIT = () => {};

/** A file's pages, drawn by the shared document viewer, with each value in question boxed; a box click outlines it. */
function ViewerKind({ node }: { node: Extract<KindNode, { type: 'viewer' }> }) {
  const preview = useFilePreviewUrl(node.fileId, true);
  const [selected, setSelected] = React.useState<string | null>(null);
  if (preview.error) return <p className="rounded-lg border p-4 text-sm text-destructive">{preview.error}</p>;
  if (!preview.url) return <KindLoading label={`Loading ${node.name ?? 'the document'}`} />;
  return <DocumentViewer url={preview.url} mime={node.mime ?? 'application/pdf'} boxes={node.boxes} selected={selected} onSelect={setSelected} className="h-full min-h-[60vh]" />;
}

/** Loading, empty and error for any kind: the same three everywhere, with the kind's own words. */
export function KindLoading({ label = 'Loading' }: { label?: string }) {
  return (
    <Card aria-busy="true" aria-label={label} data-state="loading">
      <CardHeader className="gap-2">
        <div className="h-4 w-40 animate-pulse rounded bg-muted motion-reduce:animate-none" />
        <div className="h-3 w-24 animate-pulse rounded bg-muted motion-reduce:animate-none" />
      </CardHeader>
      <CardContent>
        <div className="h-24 w-full animate-pulse rounded bg-muted motion-reduce:animate-none" />
      </CardContent>
    </Card>
  );
}

export function KindEmpty({ text }: { text: string }) {
  return (
    <Card data-state="empty">
      <CardContent className="py-6 text-center text-sm text-muted-foreground">{text}</CardContent>
    </Card>
  );
}

export function KindError({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <Card className="border-destructive/40 py-4" role="alert" data-state="error">
      <CardContent className="flex flex-col items-start gap-2 text-sm">
        <span className="font-medium text-destructive">{text}</span>
        <span className="text-muted-foreground">The service did not answer in time.</span>
        {onRetry && (
          <Button size="sm" variant="outline" onClick={onRetry}>
            Try again
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

