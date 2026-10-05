'use client';

import * as React from 'react';
import { Lock } from 'lucide-react';

import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { KeyValues, Section } from '@/components/shared/surface';
import { AccessBadge } from '@/components/status-badges';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import type { BindingSource, ModuleOperation, OperationPatch, SubjectBinding } from '@/lib/types/tool-modules';

import { BINDING_LABEL } from './module-meta';
import { SupervisionText } from './operations-table';

const SOURCES = Object.keys(BINDING_LABEL) as BindingSource[];
type Draft = { description: string; bound: boolean; binding: SubjectBinding; rate: string; requiresApproval: boolean; amountMax: string };

const draftOf = (o: ModuleOperation): Draft => ({
  description: o.description,
  bound: !!o.binding,
  binding: o.binding ?? { arg: o.input[0]?.name ?? '', bindTo: 'case.account', mode: 'equals', required: true },
  rate: String(o.rateLimitPerMin),
  requiresApproval: o.requiresApproval,
  amountMax: o.amountMax ? String(o.amountMax) : '',
});

/** One operation: its schema, the record it is bound to, and the limits the gateway enforces. Saving stages a change. */
export function OperationSheet({
  op,
  onOpenChange,
  navigation,
  onSave,
  saving,
}: {
  op: ModuleOperation | null;
  onOpenChange: (open: boolean) => void;
  navigation?: DetailSheetNavigation;
  onSave: (patch: OperationPatch) => Promise<unknown>;
  saving: boolean;
}) {
  const [d, setD] = React.useState<Draft | null>(op ? draftOf(op) : null);
  React.useEffect(() => {
    setD(op ? draftOf(op) : null);
  }, [op]);
  if (!op || !d) return <DetailSheet open={false} onOpenChange={onOpenChange} title="">{null}</DetailSheet>;

  const money = op.access === 'money_movement';
  const patch: OperationPatch = {};
  if (d.description.trim() !== op.description) patch.description = d.description;
  const nextBinding = d.bound ? d.binding : null;
  if (JSON.stringify(nextBinding) !== JSON.stringify(op.binding)) patch.binding = nextBinding;
  if (Number(d.rate) !== op.rateLimitPerMin) patch.rateLimitPerMin = Number(d.rate);
  if (d.requiresApproval !== op.requiresApproval) patch.requiresApproval = d.requiresApproval;
  if (money && Number(d.amountMax) !== (op.amountMax ?? 0)) patch.amountMax = Number(d.amountMax);
  const dirty = Object.keys(patch).length > 0;
  const rateError = !/^\d+$/.test(d.rate) || Number(d.rate) < 1 ? 'Enter a whole number of calls.' : undefined;
  const amountError = money && !(Number(d.amountMax) > 0) ? 'Enter an amount above zero.' : undefined;
  const set = (p: Partial<Draft>) => setD({ ...d, ...p });
  const setBinding = (p: Partial<SubjectBinding>) => setD({ ...d, binding: { ...d.binding, ...p } });

  return (
    <DetailSheet
      open
      onOpenChange={onOpenChange}
      title={<code className="font-mono">{op.name}</code>}
      description={op.method ? <span className="font-mono text-xs">{`${op.method} ${op.path}`}</span> : 'MCP tool'}
      tags={
        <span className="flex flex-wrap items-center gap-2">
          <AccessBadge access={op.access} />
          <SupervisionText op={op} />
          {!op.enabled && <span className="text-xs text-muted-foreground">Hidden</span>}
        </span>
      }
      navigation={navigation}
      scrollKey={op.id}
      footerActions={
        <LoadingButton size="sm" isLoading={saving} loadingText="Staging…" disabled={!dirty || !!rateError || !!amountError} onClick={() => onSave(patch)}>
          Stage change
        </LoadingButton>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="op-desc" label="Description" hint="Agents read this to decide when to call it.">
          <Textarea id="op-desc" rows={2} value={d.description} onChange={(e) => set({ description: e.target.value })} />
        </FormField>

        <Section title="Input schema" description="What the model may send. Bound fields are filled by the gateway." flush>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Field</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Required</TableHead>
                <TableHead>Description</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {op.input.map((x) => (
                <TableRow key={x.name}>
                  <TableCell>
                    <code className="font-mono text-xs">{x.name}</code>
                    {op.binding?.arg === x.name && (
                      <span className="ml-1.5 inline-flex items-center gap-0.5 text-[11px] text-muted-foreground">
                        <Lock className="size-3" /> Bound
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {x.type}
                    {x.format ? ` · ${x.format}` : ''}
                  </TableCell>
                  <TableCell className="text-xs">{x.required ? 'Yes' : 'No'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {x.description ?? '—'}
                    {x.enum && <span className="block font-mono">{x.enum.join(' | ')}</span>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Section>

        <Section
          title="Record binding"
          description="The record comes from the run’s case, never from the model. A model value that names another record is refused."
          actions={<Switch checked={d.bound} onCheckedChange={(v) => set({ bound: v })} aria-label="Bind a record from the case" disabled={!op.input.length} />}
        >
          {d.bound ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <FormField id="b-arg" label="Input">
                <Select value={d.binding.arg} onValueChange={(v) => setBinding({ arg: v })}>
                  <SelectTrigger id="b-arg" className="w-full font-mono">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {op.input.map((x) => (
                      <SelectItem key={x.name} value={x.name}>
                        <span className="font-mono">{x.name}</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
              <FormField id="b-src" label="Bound from">
                <Select value={d.binding.bindTo} onValueChange={(v) => setBinding({ bindTo: v as BindingSource })}>
                  <SelectTrigger id="b-src" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SOURCES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {BINDING_LABEL[s]} <span className="font-mono text-xs text-muted-foreground">{s}</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
              <FormField id="b-mode" label="Model may" hint={d.binding.mode === 'equals' ? 'The value is filled from the case; any other value is refused.' : 'The model may name a record that belongs to the bound one, checked by the system.'}>
                <Select value={d.binding.mode} onValueChange={(v) => setBinding({ mode: v as SubjectBinding['mode'] })}>
                  <SelectTrigger id="b-mode" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="equals">Not change it</SelectItem>
                    <SelectItem value="within">Narrow to a child record</SelectItem>
                  </SelectContent>
                </Select>
              </FormField>
              <FormField id="b-req" label="When the case has no value" hint={d.binding.required ? 'Refused as unbound.' : 'Runs without a record. Widens access: a new major version.'}>
                <Select value={d.binding.required ? 'deny' : 'allow'} onValueChange={(v) => setBinding({ required: v === 'deny' })}>
                  <SelectTrigger id="b-req" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="deny">Refuse the call</SelectItem>
                    <SelectItem value="allow">Run without it</SelectItem>
                  </SelectContent>
                </Select>
              </FormField>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No customer record. Security confirms this at review; use it only for reference data.</p>
          )}
        </Section>

        <Section title="Limits and approval">
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField id="op-rate" label="Rate limit" hint="Calls a minute, per workflow." error={rateError}>
              <Input id="op-rate" inputMode="numeric" value={d.rate} onChange={(e) => set({ rate: e.target.value })} aria-invalid={!!rateError} />
            </FormField>
            {money && (
              <FormField id="op-amount" label="Amount limit" hint="CAD per call. Raising it is a major version." error={amountError}>
                <Input id="op-amount" inputMode="decimal" value={d.amountMax} onChange={(e) => set({ amountMax: e.target.value })} aria-invalid={!!amountError} />
              </FormField>
            )}
          </div>
          {op.access !== 'read' && (
            <div className="mt-3 flex items-start justify-between gap-4 rounded-md border p-3">
              <div>
                <p className="text-sm font-medium">Every call waits for an approval</p>
                <p className="text-xs text-muted-foreground">
                  {money ? 'Money movement always needs a person, and the approver must differ from whoever drafted the action.' : 'Off: only a gate policy’s approval token lets the call run. Turning it off is a major version.'}
                </p>
              </div>
              <Switch checked={d.requiresApproval} disabled={money} onCheckedChange={(v) => set({ requiresApproval: v })} aria-label="Every call waits for an approval" />
            </div>
          )}
        </Section>

        <Section title="Gateway handling">
          <KeyValues
            rows={[
              ['Masked in responses', op.maskedOutput.length ? <code className="font-mono text-xs">{op.maskedOutput.join(', ')}</code> : 'Nothing'],
              ['Idempotency', op.idempotent ? 'Key runId:actionId; a retry never writes twice' : 'Not needed for reads'],
              ['Workflows approved', String(op.approvedWorkflows)],
            ]}
          />
        </Section>
      </div>
    </DetailSheet>
  );
}
