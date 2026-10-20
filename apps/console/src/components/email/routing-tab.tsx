'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { FormField, StopRowClick } from '@/components/shared/form-field';
import { SettingsSection } from '@/components/shared/settings-section';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import type { CasePriority, EmailWorkflowConfig, RouteRule } from '@/lib/types/cases';

import { ConfigNote } from './config-note';

const PRIORITIES: CasePriority[] = ['urgent', 'high', 'normal', 'low'];
type Row = RouteRule & { intentName: string };

/** Routing & SLAs tab: per intent, which queue gets the case, at what priority, and how long the team has. */
export function RoutingTab({ config, onChange, queues }: { config: EmailWorkflowConfig; onChange: (c: EmailWorkflowConfig) => void; queues: string[] }) {
  const patch = (intentId: string, p: Partial<RouteRule>) => onChange({ ...config, routes: config.routes.map((r) => (r.intentId === intentId ? { ...r, ...p } : r)) });

  const columns: ColumnDef<Row>[] = [
    {
      accessorKey: 'intentName',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Intent" />,
      cell: ({ row }) => <span className="font-medium whitespace-nowrap">{row.original.intentName}</span>,
      enableHiding: false,
    },
    {
      accessorKey: 'queue',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Queue" />,
      cell: ({ row }) => (
        <StopRowClick align="start">
          <Select value={row.original.queue} onValueChange={(v) => patch(row.original.intentId, { queue: v })}>
            <SelectTrigger size="sm" className="w-48" aria-label={`Queue for ${row.original.intentName}`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {queues.map((q) => (
                <SelectItem key={q} value={q}>
                  {q}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </StopRowClick>
      ),
      enableSorting: false,
    },
    {
      accessorKey: 'priority',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Priority" />,
      cell: ({ row }) => (
        <StopRowClick align="start">
          <Select value={row.original.priority} onValueChange={(v) => patch(row.original.intentId, { priority: v as CasePriority })}>
            <SelectTrigger size="sm" className="w-28 capitalize" aria-label={`Priority for ${row.original.intentName}`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PRIORITIES.map((p) => (
                <SelectItem key={p} value={p} className="capitalize">
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </StopRowClick>
      ),
      enableSorting: false,
    },
    {
      accessorKey: 'slaHours',
      header: ({ column }) => <DataTableColumnHeader column={column} title="SLA (hours)" />,
      cell: ({ row }) => (
        <StopRowClick align="start">
          <SlaHoursInput key={`${row.original.intentId}-${row.original.slaHours}`} intentName={row.original.intentName} value={row.original.slaHours} onCommit={(n) => patch(row.original.intentId, { slaHours: n })} />
        </StopRowClick>
      ),
      enableSorting: false,
    },
    {
      accessorKey: 'businessHours',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Business hours only" />,
      cell: ({ row }) => (
        <StopRowClick align="start">
          <Switch checked={row.original.businessHours} onCheckedChange={(v) => patch(row.original.intentId, { businessHours: v })} aria-label={`Business hours only for ${row.original.intentName}`} />
        </StopRowClick>
      ),
      enableSorting: false,
    },
  ];

  const rows: Row[] = config.routes.map((r) => ({ ...r, intentName: config.intents.find((i) => i.id === r.intentId)?.name ?? r.intentId }));

  return (
    <div className="flex flex-col gap-4" data-testid="routing-tab">
      <ConfigNote>Each new case lands in a queue with a priority and an SLA clock. Business-hours SLAs pause overnight and on weekends.</ConfigNote>
      <DataTableWithViews columns={columns} data={rows} getRowId={(r) => r.intentId} hideViewSwitcher searchColumn="intentName" searchPlaceholder="Search intents…" />
      <SettingsSection title="When the agent is unsure" description="Mail the classifier cannot place confidently goes to a person instead of a guess.">
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="fallback-queue" label="Fallback queue">
            <Select value={config.fallbackQueue} onValueChange={(v) => onChange({ ...config, fallbackQueue: v })}>
              <SelectTrigger id="fallback-queue" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {queues.map((q) => (
                  <SelectItem key={q} value={q}>
                    {q}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="confidence" label={`Minimum confidence · ${Math.round(config.confidenceThreshold * 100)}%`} hint="Lower sends fewer emails to the fallback queue and more to the wrong one.">
            <Slider
              id="confidence"
              min={50}
              max={95}
              step={1}
              value={[Math.round(config.confidenceThreshold * 100)]}
              onValueChange={([v]) => onChange({ ...config, confidenceThreshold: v / 100 })}
              aria-label="Minimum confidence"
            />
          </FormField>
        </div>
      </SettingsSection>
    </div>
  );
}

/** SLA hours, 1 to 240. An out-of-range value stays in the field with an inline error instead of reverting. */
function SlaHoursInput({ intentName, value, onCommit }: { intentName: string; value: number; onCommit: (n: number) => void }) {
  const [text, setText] = React.useState(String(value));
  const [error, setError] = React.useState<string | null>(null);
  const id = `sla-${intentName.replace(/\W+/g, '-').toLowerCase()}`;
  const check = (raw: string) => {
    const n = Number(raw);
    if (!raw.trim() || !Number.isInteger(n)) return 'Enter whole hours.';
    if (n < 1) return 'At least 1 hour.';
    if (n > 240) return 'At most 240 hours.';
    return null;
  };
  return (
    <div className="flex flex-col gap-1">
      <Input
        id={id}
        type="number"
        min={1}
        max={240}
        className="h-8 w-20 tabular-nums"
        aria-label={`SLA hours for ${intentName}`}
        aria-invalid={!!error}
        aria-describedby={error ? `${id}-error` : undefined}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          if (error) setError(check(e.target.value));
        }}
        onBlur={() => {
          const err = check(text);
          setError(err);
          if (!err && Number(text) !== value) onCommit(Number(text));
        }}
      />
      {error && (
        <span id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </span>
      )}
    </div>
  );
}
