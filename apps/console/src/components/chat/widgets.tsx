'use client';

import * as React from 'react';
import Link from 'next/link';
import { Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';
import { AppWindow, ArrowUpRight, CheckCircle2, Clock, ShieldCheck, XCircle } from 'lucide-react';

import { RiskBadge } from '@/components/status-badges';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { type ChartConfig, ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { relativeTime } from '@/lib/format';
import type { ApprovalWidget, ChartWidget, ChatWidget, FormWidget, MetricWidget, RecordWidget, TableWidget, WidgetAction, WidgetKind } from '@/lib/types/chat';
import { cn } from '@/lib/utils';

/**
 * In-chat views of MCP App results. In production each app ships its own UI, rendered in a sandboxed iframe
 * served through the tool gateway, and talks to the chat only through postMessage (the MCP Apps protocol).
 * The mock renders the same payloads with native components; the frame, provenance line and action contract
 * are the parts that carry over.
 */
export interface WidgetProps<W extends ChatWidget = ChatWidget> {
  widget: W;
  /** Undefined when the conversation is read-only (someone else's, or archived). */
  onAction?: (action: WidgetAction) => Promise<unknown>;
}

function WidgetFrame({ widget, actions, children }: { widget: ChatWidget; actions?: React.ReactNode; children: React.ReactNode }) {
  const href = 'href' in widget ? widget.href : undefined;
  return (
    <section className="overflow-hidden rounded-lg border bg-card" aria-label={widget.title}>
      <header className="flex items-center gap-2 border-b px-3 py-2">
        <AppWindow className="size-3.5 shrink-0 text-muted-foreground" />
        <h4 className="min-w-0 flex-1 truncate text-sm font-medium">{widget.title}</h4>
        {actions}
        {href && (
          <Button asChild variant="ghost" size="sm" className="h-6 gap-1 px-2 text-xs">
            <Link href={href}>
              Open <ArrowUpRight className="size-3" />
            </Link>
          </Button>
        )}
      </header>
      <div className="min-w-0">{children}</div>
      <footer className="flex flex-wrap gap-x-2 border-t bg-muted/30 px-3 py-1.5 text-[11px] text-muted-foreground">
        <span>{widget.app}</span>
        <span>·</span>
        <span className="font-mono">{widget.tool}</span>
        <span>·</span>
        <span>Data as of {relativeTime(widget.asOf)}</span>
      </footer>
    </section>
  );
}

function TableView({ widget }: WidgetProps<TableWidget>) {
  return (
    <WidgetFrame widget={widget}>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {widget.columns.map((c) => (
                <TableHead key={c.key} className={cn('h-8 text-xs', c.align === 'right' && 'text-right')}>
                  {c.label}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {widget.rows.map((r, i) => (
              <TableRow key={i}>
                {widget.columns.map((c) => (
                  <TableCell key={c.key} className={cn('py-1.5 text-xs whitespace-nowrap', c.align === 'right' && 'text-right tabular-nums', c.tone && Number(r[c.key]) > 0 && 'font-medium text-destructive')}>
                    {r[c.key]}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </WidgetFrame>
  );
}

const CHART_COLORS = ['var(--chart-1)', 'var(--chart-4)', 'var(--chart-2)', 'var(--chart-3)'];

function ChartView({ widget }: WidgetProps<ChartWidget>) {
  const config = Object.fromEntries(widget.series.map((s, i) => [s.key, { label: s.label, color: CHART_COLORS[i % CHART_COLORS.length] }])) satisfies ChartConfig;
  const axes = (
    <>
      <CartesianGrid vertical={false} />
      <XAxis dataKey={widget.xKey} tickLine={false} axisLine={false} tickMargin={8} fontSize={11} interval={0} tickFormatter={(v: string) => (v.length > 12 ? `${v.slice(0, 11)}…` : v)} />
      <YAxis tickLine={false} axisLine={false} width={widget.yLabel ? 44 : 32} fontSize={11} allowDecimals={false} label={widget.yLabel ? { value: widget.yLabel, angle: -90, position: 'insideLeft', fontSize: 11, style: { textAnchor: 'middle', fill: 'var(--muted-foreground)' } } : undefined} />
      <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
      <ChartLegend content={<ChartLegendContent />} />
    </>
  );
  return (
    <WidgetFrame widget={widget}>
      <div className="p-3">
        <ChartContainer
          config={config}
          className="aspect-auto h-56 w-full"
          role="img"
          aria-label={`${widget.title}. ${widget.chart === 'bar' ? 'Bar' : 'Line'} chart of ${widget.series.map((x) => x.label).join(' and ')}${widget.yLabel ? ` (${widget.yLabel.toLowerCase()})` : ''} by ${widget.xKey}: ${widget.data.map((d) => `${d[widget.xKey]} ${widget.series.map((x) => `${d[x.key]} ${x.label.toLowerCase()}`).join(', ')}`).join('; ')}.`}
        >
          {widget.chart === 'bar' ? (
            <BarChart data={widget.data} margin={{ left: 0, right: 8, top: 8 }}>
              {axes}
              {widget.series.map((s) => (
                <Bar key={s.key} dataKey={s.key} fill={`var(--color-${s.key})`} radius={3} />
              ))}
            </BarChart>
          ) : (
            <LineChart data={widget.data} margin={{ left: 0, right: 8, top: 8 }}>
              {axes}
              {widget.series.map((s) => (
                <Line key={s.key} dataKey={s.key} type="monotone" stroke={`var(--color-${s.key})`} strokeWidth={2} dot={false} />
              ))}
            </LineChart>
          )}
        </ChartContainer>
      </div>
    </WidgetFrame>
  );
}

function Fields({ fields }: { fields: { label: string; value: string }[] }) {
  return (
    <dl className="grid gap-x-4 gap-y-2 p-3 text-sm sm:grid-cols-[minmax(8rem,auto)_1fr]">
      {fields.map((f) => (
        <React.Fragment key={f.label}>
          <dt className="text-xs text-muted-foreground sm:pt-0.5">{f.label}</dt>
          <dd className="min-w-0 break-words">{f.value}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function RecordView({ widget }: WidgetProps<RecordWidget>) {
  return (
    <WidgetFrame widget={widget} actions={widget.status && <span className="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">{widget.status}</span>}>
      {widget.subtitle && <p className="px-3 pt-3 text-xs text-muted-foreground">{widget.subtitle}</p>}
      <Fields fields={widget.fields} />
    </WidgetFrame>
  );
}

function MetricView({ widget }: WidgetProps<MetricWidget>) {
  return (
    <WidgetFrame widget={widget}>
      <div className="grid grid-cols-2 gap-px bg-border lg:grid-cols-4">
        {widget.metrics.map((m) => (
          <div key={m.label} className="bg-card p-3">
            <p className="text-xs text-muted-foreground">{m.label}</p>
            <p className="text-xl font-semibold tabular-nums">{m.value}</p>
            {m.delta && <p className={cn('text-xs', m.tone === 'good' ? 'text-emerald-700 dark:text-emerald-300' : m.tone === 'bad' ? 'text-destructive' : 'text-muted-foreground')}>{m.delta}</p>}
          </div>
        ))}
      </div>
    </WidgetFrame>
  );
}

const APPROVAL_STATE: Record<ApprovalWidget['state'], { label: string; icon: typeof Clock; cls: string }> = {
  pending: { label: 'Waiting for approval', icon: Clock, cls: 'text-amber-700 dark:text-amber-300' },
  awaiting_second: { label: 'Waiting on a second approver', icon: ShieldCheck, cls: 'text-sky-700 dark:text-sky-300' },
  approved: { label: 'Approved', icon: CheckCircle2, cls: 'text-emerald-700 dark:text-emerald-300' },
  rejected: { label: 'Rejected', icon: XCircle, cls: 'text-destructive' },
};

function ApprovalView({ widget, onAction }: WidgetProps<ApprovalWidget>) {
  const [busy, setBusy] = React.useState<'approve' | 'reject' | null>(null);
  const [rejecting, setRejecting] = React.useState(false);
  const [confirming, setConfirming] = React.useState(false);
  const [reason, setReason] = React.useState('');
  const s = APPROVAL_STATE[widget.state];
  const open = widget.state === 'pending';
  const act = async (a: WidgetAction) => {
    setBusy(a.type === 'approve' ? 'approve' : 'reject');
    try {
      await onAction?.(a);
      setRejecting(false);
      setReason('');
    } finally {
      setBusy(null);
    }
  };
  return (
    <WidgetFrame widget={widget} actions={<RiskBadge risk={widget.risk} />}>
      <div className="space-y-1 px-3 pt-3">
        <p className="text-sm font-medium">{widget.action}</p>
        <p className="text-xs text-muted-foreground">{widget.summary}</p>
      </div>
      <Fields fields={widget.fields} />
      <div className="flex flex-wrap items-center gap-2 border-t px-3 py-2">
        <span className={cn('inline-flex items-center gap-1.5 text-xs font-medium', s.cls)}>
          <s.icon className="size-3.5" /> {s.label}
          {widget.decidedBy && widget.state !== 'pending' && <span className="font-normal text-muted-foreground">by {widget.decidedBy}</span>}
        </span>
        <Link href={`/reviews?review=${widget.reviewId}`} className="font-mono text-xs text-muted-foreground underline-offset-4 hover:underline">
          {widget.reviewId}
        </Link>
        {open && onAction && (
          <span className="ml-auto flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setRejecting(true)} disabled={!!busy}>
              Reject
            </Button>
            <LoadingButton size="sm" isLoading={busy === 'approve'} loadingText="Approving…" onClick={() => (widget.consequence ? setConfirming(true) : act({ type: 'approve' }))} disabled={!!busy}>
              Approve
            </LoadingButton>
          </span>
        )}
      </div>
      {widget.consequence && (
        <ConfirmActionDialog
          open={confirming}
          onOpenChange={setConfirming}
          title={`${widget.action}?`}
          consequence={widget.consequence}
          details={widget.fields}
          runsNow
          confirmLabel="Approve and run"
          isPending={busy === 'approve'}
          onConfirm={() => act({ type: 'approve' })}
        />
      )}
      {widget.state === 'rejected' && widget.reason && <p className="border-t px-3 py-2 text-xs text-muted-foreground">Reason: {widget.reason}</p>}
      <DialogShell
        open={rejecting}
        onOpenChange={(o) => !busy && setRejecting(o)}
        size="sm"
        title={`Reject ${widget.reviewId}`}
        description="The drafted action is discarded and the agent is told why. The reason is kept on the review."
        footer={
          <>
            <Button variant="outline" onClick={() => setRejecting(false)} disabled={!!busy}>
              Cancel
            </Button>
            <LoadingButton variant="destructive" isLoading={busy === 'reject'} loadingText="Rejecting…" disabled={!reason.trim()} onClick={() => act({ type: 'reject', reason: reason.trim() })}>
              Reject
            </LoadingButton>
          </>
        }
      >
        <FormField id="reject-reason" label="Reason">
          <Textarea id="reject-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. The merchant already refunded the second charge" autoFocus />
        </FormField>
      </DialogShell>
    </WidgetFrame>
  );
}

function FormView({ widget, onAction }: WidgetProps<FormWidget>) {
  const [values, setValues] = React.useState<Record<string, string>>(() => Object.fromEntries(widget.fields.map((f) => [f.key, widget.values?.[f.key] ?? f.value ?? ''])));
  const [busy, setBusy] = React.useState(false);
  const submitted = widget.state === 'submitted';
  const missing = widget.fields.some((f) => f.required && !values[f.key]?.trim());
  const set = (k: string, v: string) => setValues((s) => ({ ...s, [k]: v }));
  const submit = async () => {
    setBusy(true);
    try {
      await onAction?.({ type: 'submit', values });
    } finally {
      setBusy(false);
    }
  };
  return (
    <WidgetFrame widget={widget}>
      <form
        className="space-y-3 p-3"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <p className="text-xs text-muted-foreground">{widget.description}</p>
        <fieldset disabled={submitted || busy || !onAction} className="grid gap-3 sm:grid-cols-2">
          {widget.fields.map((f) => {
            const fid = `${widget.id}-${f.key}`;
            const error = !submitted && f.required && !values[f.key]?.trim() ? `${f.label} is required.` : undefined;
            return (
              <FormField key={f.key} id={fid} label={f.label} optional={!f.required} error={error} className={f.type === 'textarea' ? 'sm:col-span-2' : undefined}>
                {f.type === 'select' ? (
                  <Select value={values[f.key]} onValueChange={(v) => set(f.key, v)} disabled={submitted || busy || !onAction}>
                    <SelectTrigger id={fid} className="w-full" aria-invalid={!!error}>
                      <SelectValue placeholder="Choose…" />
                    </SelectTrigger>
                    <SelectContent>
                      {f.options?.map((o) => (
                        <SelectItem key={o} value={o}>
                          {o}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : f.type === 'textarea' ? (
                  <Textarea id={fid} rows={2} value={values[f.key]} onChange={(e) => set(f.key, e.target.value)} aria-invalid={!!error} />
                ) : (
                  <Input id={fid} value={values[f.key]} onChange={(e) => set(f.key, e.target.value)} aria-invalid={!!error} />
                )}
              </FormField>
            );
          })}
        </fieldset>
        {submitted ? (
          <p className="flex items-center gap-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-300">
            <CheckCircle2 className="size-3.5" /> {widget.result}
          </p>
        ) : (
          onAction && (
            <div className="flex items-center justify-end gap-3">
              {missing && <span className="text-xs text-muted-foreground">Fill in the required fields to continue.</span>}
              <LoadingButton type="submit" size="sm" isLoading={busy} loadingText="Submitting…" disabled={missing}>
                {widget.submitLabel}
              </LoadingButton>
            </div>
          )
        )}
      </form>
    </WidgetFrame>
  );
}

const REGISTRY: { [K in WidgetKind]: React.ComponentType<WidgetProps<Extract<ChatWidget, { kind: K }>>> } = {
  table: TableView,
  chart: ChartView,
  record: RecordView,
  metric: MetricView,
  approval: ApprovalView,
  form: FormView,
};

/** Renders any widget by kind. A new MCP App view is one entry in the registry. */
export function WidgetView({ widget, onAction }: WidgetProps) {
  const View = REGISTRY[widget.kind] as React.ComponentType<WidgetProps>;
  return <View widget={widget} onAction={onAction} />;
}
