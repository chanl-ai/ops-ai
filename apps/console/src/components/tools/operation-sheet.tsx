'use client';

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle, CheckCircle2, KeyRound } from 'lucide-react';

import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { KeyValues, Section } from '@/components/shared/surface';
import { AccessBadge } from '@/components/status-badges';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useTeam } from '@/hooks/use-team';
import { ApiError } from '@/lib/api/contract';
import type { ToolAccess } from '@/lib/types/domain';
import type { BindingSource, HttpOperationInput, ModuleOperation, OperationPatch, SubjectBinding } from '@/lib/types/tool-modules';

import { HttpOperationBuilder } from './http-operation-builder';
import { fieldDrafts, InputSchemaEditor, schemaOf, type FieldDraft } from './input-schema-editor';
import { BINDING_LABEL } from './module-meta';
import { SupervisionText } from './operations-table';

const SOURCES = Object.keys(BINDING_LABEL) as BindingSource[];
type Draft = { description: string; bound: boolean; binding: SubjectBinding; rate: string; requiresApproval: boolean; amountMax: string; approvers: 1 | 2; approverTeam: string; stepUp: boolean; access: ToolAccess; input: FieldDraft[]; http: HttpOperationInput; transform: string; timeout: string };

const baseOf = (endpoint: string) => endpoint.replace(/\/+$/, '');

/** Input fields the call never names: `{name}` in the path, or `{{name}}` / `{{ name }}` in a header or the body. */
export function unusedInputs(op: ModuleOperation, http: HttpOperationInput): string[] {
  const text = [http.url, http.body ?? '', ...http.headers.map((h) => h.value)].join('\n');
  return op.input.map((f) => f.name).filter((n) => ![`{${n}}`, `{{${n}}}`, `{{ ${n} }}`].some((p) => text.includes(p)));
}

const draftOf = (o: ModuleOperation, endpoint: string): Draft => ({
  description: o.description,
  bound: !!o.binding,
  binding: o.binding ?? { arg: o.input[0]?.name ?? '', bindTo: 'case.account', mode: 'equals', required: true },
  rate: String(o.rateLimitPerMin),
  requiresApproval: o.requiresApproval,
  amountMax: o.amountMax ? String(o.amountMax) : '',
  approvers: o.approvers,
  approverTeam: o.approverTeam,
  stepUp: !!o.stepUp,
  access: o.access,
  input: fieldDrafts(o.input),
  http: { name: o.name, description: o.description, access: o.access, method: o.method ?? 'GET', url: `${baseOf(endpoint)}${o.path ?? ''}`, headers: o.headers.map((h) => ({ ...h })), body: o.body ?? '' },
  transform: o.responseTransform ?? '',
  timeout: o.timeoutMs ? String(o.timeoutMs / 1000) : '',
});

/** One operation: its schema, the record it is bound to, and the limits the gateway enforces. Saving stages a change. */
export function OperationSheet({
  op,
  endpoint,
  stagedCall,
  onOpenChange,
  navigation,
  onSave,
  saving,
  policyOnly,
}: {
  op: ModuleOperation | null;
  /** The module endpoint every operation's path hangs off; the URL's origin cannot change here. */
  endpoint: string;
  /** The operation's call (method, path or body) has a staged change; what the sheet shows is not yet what calls run. */
  stagedCall?: boolean;
  onOpenChange: (open: boolean) => void;
  navigation?: DetailSheetNavigation;
  onSave: (patch: OperationPatch) => Promise<unknown>;
  saving: boolean;
  /** Opened from the workbench, which edits the call and the input itself: the sheet keeps the policy (c-088). */
  policyOnly?: boolean;
}) {
  const [d, setD] = React.useState<Draft | null>(op ? draftOf(op, endpoint) : null);
  // The service's refusal of the input schema, by field name, shown on that row.
  const [inputErrors, setInputErrors] = React.useState<Record<string, string>>({});
  const { teams } = useTeam();
  React.useEffect(() => {
    setD(op ? draftOf(op, endpoint) : null);
    setInputErrors({});
  }, [op, endpoint]);
  if (!op || !d) return <DetailSheet open={false} onOpenChange={onOpenChange} title="">{null}</DetailSheet>;

  const write = d.access === 'write';
  // Two approvers means a person approves every call, so the switch cannot turn per-call approval off.
  const twoApprovers = write && d.approvers === 2;
  // The person's own teams, plus the operation's current approving team when they are not in it.
  const teamName = (id: string) => teams.find((t) => t.id === id)?.name ?? id;
  const teamChoices = [...teams.map((t) => t.id), ...(teams.some((t) => t.id === op.approverTeam) ? [] : [op.approverTeam])];
  const patch: OperationPatch = {};
  if (d.description.trim() !== op.description) patch.description = d.description;
  const nextBinding = d.bound ? d.binding : null;
  if (JSON.stringify(nextBinding) !== JSON.stringify(op.binding)) patch.binding = nextBinding;
  if (Number(d.rate) !== op.rateLimitPerMin) patch.rateLimitPerMin = Number(d.rate);
  if (d.requiresApproval !== op.requiresApproval) patch.requiresApproval = d.requiresApproval;
  if (write && d.amountMax.trim() && Number(d.amountMax) !== (op.amountMax ?? 0)) patch.amountMax = Number(d.amountMax);
  if (write && d.approvers !== op.approvers) patch.approvers = d.approvers;
  if (write && d.approverTeam !== op.approverTeam) patch.approverTeam = d.approverTeam;
  if (write && d.stepUp !== !!op.stepUp) patch.stepUp = d.stepUp;
  if (d.access !== op.access) patch.access = d.access;
  const input = schemaOf(d.input);
  if (JSON.stringify(input) !== JSON.stringify(schemaOf(fieldDrafts(op.input)))) patch.input = input;
  // The HTTP call: staged like every other edit, and calls keep the published call until the next publish.
  const http = op.executor === 'http';
  const base = baseOf(endpoint);
  const urlError = http && d.http.url !== base && !d.http.url.startsWith(`${base}/`) ? `Keep the module endpoint, ${base}. A second system is a second module.` : undefined;
  const secs = d.timeout.trim();
  const timeoutError = secs && !(Number(secs) >= 1 && Number(secs) <= 120) ? 'Enter 1 to 120 seconds, or leave it blank for the module timeout.' : undefined;
  if (http) {
    if (d.http.method !== op.method) patch.method = d.http.method;
    const path = d.http.url.slice(base.length) || '/';
    if (!urlError && path !== op.path) patch.path = path;
    const headers = d.http.headers.filter((h) => h.key.trim()).map((h) => ({ key: h.key.trim(), value: h.value.trim() }));
    if (JSON.stringify(headers) !== JSON.stringify(op.headers)) patch.headers = headers;
    if ((d.http.body ?? '').trim() !== (op.body ?? '')) patch.body = (d.http.body ?? '').trim();
    if (d.transform.trim() !== (op.responseTransform ?? '')) patch.responseTransform = d.transform.trim() || null;
    const ms = secs ? Math.round(Number(secs) * 1000) : null;
    if (!timeoutError && ms !== (op.timeoutMs ?? null)) patch.timeoutMs = ms;
  }
  const unused = http ? unusedInputs(op, d.http) : [];
  const dirty = Object.keys(patch).length > 0;
  const rateError = !/^\d+$/.test(d.rate) || Number(d.rate) < 1 ? 'Enter a whole number of calls.' : undefined;
  const amountError = write && d.amountMax.trim() && !(Number(d.amountMax) > 0) ? 'Enter an amount above zero, or leave it blank for no limit.' : undefined;
  const set = (p: Partial<Draft>) => setD({ ...d, ...p });
  const setBinding = (p: Partial<SubjectBinding>) => setD({ ...d, binding: { ...d.binding, ...p } });

  return (
    <DetailSheet
      open
      onOpenChange={onOpenChange}
      title={<code className="font-mono">{op.name}</code>}
      description={
        op.method ? (
          <span className="font-mono text-xs" data-testid="op-call">
            {`${op.method} ${op.path}`}
            {stagedCall && <span className="font-sans text-warning-text"> · staged; calls run the published call until you publish</span>}
          </span>
        ) : (
          'MCP tool'
        )
      }
      tags={
        <span className="flex flex-wrap items-center gap-2">
          <AccessBadge access={op.access} />
          <SupervisionText op={op} />
          {write && (
            <span className="text-xs text-muted-foreground" data-testid="op-approval-policy">
              Approved by {teamName(op.approverTeam)}
            </span>
          )}
          {!op.enabled && <span className="text-xs text-muted-foreground">Hidden</span>}
        </span>
      }
      navigation={navigation}
      scrollKey={op.id}
      footerActions={
        <LoadingButton
          size="sm"
          isLoading={saving}
          loadingText="Staging…"
          disabled={!dirty || !!rateError || !!amountError || !!urlError || !!timeoutError}
          onClick={() =>
            onSave(patch).then(
              () => setInputErrors({}),
              (e: unknown) => {
                const field = e instanceof ApiError ? String(e.details?.field ?? '') : '';
                if (field.startsWith('input.')) setInputErrors({ [field.slice(6)]: (e as Error).message });
              },
            )
          }
          data-testid="op-stage"
        >
          Stage change
        </LoadingButton>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="op-desc" label="Description" hint="Agents read this to decide when to call it.">
          <Textarea id="op-desc" rows={2} value={d.description} onChange={(e) => set({ description: e.target.value })} />
        </FormField>

        {http && policyOnly && (
          <FormField id="op-timeout" label="Timeout" optional hint="Seconds, 1 to 120. Blank uses the module timeout." error={timeoutError}>
            <Input id="op-timeout" inputMode="numeric" value={d.timeout} onChange={(e) => set({ timeout: e.target.value })} className="w-28" aria-invalid={!!timeoutError} />
          </FormField>
        )}

        {http && !policyOnly && (
          <Section title="HTTP call" description="Calls keep the published call until a staged change is published. A method, path or body change is a major version." >
            <div className="flex flex-col gap-4" data-testid="op-http">
              <HttpOperationBuilder callOnly value={d.http} onChange={(v) => set({ http: v })} errors={{ url: urlError }} />
              {unused.length > 0 && (
                <p className="flex items-start gap-1.5 text-xs text-warning-text" data-testid="op-unused-inputs">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                  <span>
                    {unused.join(', ')} {unused.length === 1 ? 'is an input' : 'are inputs'} of this operation, but the URL, headers and body never use {unused.length === 1 ? 'it' : 'them'}. Agents may send {unused.length === 1 ? 'it' : 'them'} and the call drops {unused.length === 1 ? 'it' : 'them'}.
                  </span>
                </p>
              )}
              <FormField id="op-transform" label="Response transform" optional hint="A Jinja2 template over the answer as data, e.g. {{ data.balance }}. If it fails on a real answer, the agent gets the answer and the error.">
                <Textarea id="op-transform" rows={3} value={d.transform} onChange={(e) => set({ transform: e.target.value })} className="font-mono text-xs" placeholder={'e.g. {"balance": {{ data.balance }}}'} />
              </FormField>
              <FormField id="op-timeout" label="Timeout" optional hint="Seconds, 1 to 120. Blank uses the module timeout." error={timeoutError}>
                <Input id="op-timeout" inputMode="numeric" value={d.timeout} onChange={(e) => set({ timeout: e.target.value })} className="w-28" aria-invalid={!!timeoutError} />
              </FormField>
            </div>
          </Section>
        )}

        {!policyOnly && (
          <Section title="Input schema" description="What the model may send. Bound fields are filled by the gateway.">
            <InputSchemaEditor value={d.input} onChange={(v) => set({ input: v })} boundArg={op.binding?.arg} errors={inputErrors} />
          </Section>
        )}

        {(op.secrets?.length ?? 0) > 0 && (
          <Section title="Secrets" description="Credentials this operation's headers and URL read at call time. Values are never shown here.">
            <ul className="flex flex-col gap-1.5" data-testid="op-secrets">
              {op.secrets!.map((sec) => (
                <li key={sec.name} className="flex items-center gap-2 text-sm">
                  <KeyRound className="size-3.5 text-muted-foreground" />
                  <code className="font-mono text-xs">{sec.name}</code>
                  {sec.set && sec.available === false ? (
                    <Link href="/settings/security/secrets" className="inline-flex items-center gap-1 text-xs text-warning-text underline-offset-4 hover:underline">
                      <AlertTriangle className="size-3.5" /> Not available to this module&apos;s team
                    </Link>
                  ) : sec.set ? (
                    <span className="inline-flex items-center gap-1 text-xs text-success-text">
                      <CheckCircle2 className="size-3.5" /> Set
                    </span>
                  ) : (
                    <Link href="/settings/security/secrets" className="inline-flex items-center gap-1 text-xs text-warning-text underline-offset-4 hover:underline">
                      <AlertTriangle className="size-3.5" /> {sec.name} not set
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </Section>
        )}

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
            <FormField id="op-access" label="Access" hint="Whether a call changes data. Any change is a major version; a write waits for an approval.">
              <Select value={d.access} onValueChange={(v) => set(v === 'write' ? { access: 'write', requiresApproval: true } : { access: 'read' })}>
                <SelectTrigger id="op-access" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="read">Read</SelectItem>
                  <SelectItem value="write">Write</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
            <FormField id="op-rate" label="Rate limit" hint="Calls a minute for this operation, across every caller." error={rateError}>
              <Input id="op-rate" inputMode="numeric" value={d.rate} onChange={(e) => set({ rate: e.target.value })} aria-invalid={!!rateError} />
            </FormField>
            {write && (
              <FormField id="op-amount" label="Amount limit" optional hint="CAD per call, for a write that carries an amount. Raising it is a major version." error={amountError}>
                <Input id="op-amount" inputMode="decimal" value={d.amountMax} onChange={(e) => set({ amountMax: e.target.value })} aria-invalid={!!amountError} />
              </FormField>
            )}
          </div>
          {write && (
            <div className="mt-3 flex items-start justify-between gap-4 rounded-md border p-3">
              <div>
                <p className="text-sm font-medium">Every call waits for an approval</p>
                <p className="text-xs text-muted-foreground">
                  {twoApprovers ? 'Two different people approve every call, as the operation’s approval policy requires.' : 'Off: only a gate policy’s approval token lets the call run. Turning it off is a major version.'}
                </p>
              </div>
              <Switch checked={d.requiresApproval || twoApprovers} disabled={twoApprovers} onCheckedChange={(v) => set({ requiresApproval: v })} aria-label="Every call waits for an approval" />
            </div>
          )}
          {write && (
            <div className="mt-3 grid gap-3 sm:grid-cols-2" data-testid="op-approval-controls">
              <FormField id="op-approvers" label="Approvals per call" hint="Fewer approvals is a major version that Security reviews.">
                <Select value={String(d.approvers)} onValueChange={(v) => set(v === '2' ? { approvers: 2, requiresApproval: true } : { approvers: 1 })}>
                  <SelectTrigger id="op-approvers" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">One person</SelectItem>
                    <SelectItem value="2">Two different people</SelectItem>
                  </SelectContent>
                </Select>
              </FormField>
              <FormField id="op-approver-team" label="Approving team" hint="Approvals come from this team. Changing it is a major version.">
                <Select value={d.approverTeam} onValueChange={(v) => set({ approverTeam: v })}>
                  <SelectTrigger id="op-approver-team" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {teamChoices.map((id) => (
                      <SelectItem key={id} value={id}>
                        {teamName(id)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
              <div className="flex items-start justify-between gap-4 rounded-md border p-3 sm:col-span-2">
                <div>
                  <p className="text-sm font-medium">Approving asks for a step-up</p>
                  <p className="text-xs text-muted-foreground">{twoApprovers ? 'Always on when two people approve.' : 'The approver confirms their password before deciding. Changing it is a major version.'}</p>
                </div>
                <Switch checked={d.stepUp || twoApprovers} disabled={twoApprovers} onCheckedChange={(v) => set({ stepUp: v })} aria-label="Approving asks for a step-up" />
              </div>
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
