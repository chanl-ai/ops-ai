'use client';

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle, ArrowRight, Plus, ShieldAlert, ShieldCheck, X } from 'lucide-react';

import { EvalSummaryLine } from '@/components/evals/eval-meta';
import { VALIDATION_STATUS_LABEL } from '@/components/model-risk/model-risk-meta';
import { RunAsBar } from '@/components/run-as/run-as-bar';
import { FieldSectionLabel } from '@/components/shared/field-row';
import { LoadingButton } from '@/components/shared/loading-button';
import { RiskBadge } from '@/components/status-badges';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { plural } from '@/lib/format';
import type { Review, ReviewDecision, Risk, ValidationSummary } from '@/lib/types/domain';
import type { AgentEvalPin } from '@/lib/types/evals';
import { cn } from '@/lib/utils';
import type { ConditionInput } from '@/lib/types/model-risk';
import type { RunAsPrincipal } from '@/lib/types/run-as';

const SCOPE_LABEL = { initial: 'First validation', periodic: 'Periodic revalidation', tier_change: 'Tier change' } as const;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <FieldSectionLabel>{title}</FieldSectionLabel>
      {children}
    </section>
  );
}

/** Read-only body of a `model_validation` review: what is being validated, the evidence, and the outcome once decided. */
export function ModelValidationBody({ review }: { review: Review }) {
  const mv = review.modelValidation!;
  return (
    <div className="flex flex-col gap-6" data-testid="model-validation-body">
      <Section title={SCOPE_LABEL[mv.scope]}>
        <div className="rounded-lg border border-primary/25 bg-primary/5 p-4">
          <p className="text-sm font-medium">{mv.note}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="capitalize">{mv.entryType}</span> · <span className="font-medium text-foreground">{mv.entryName}</span> ·
            {mv.scope === 'tier_change' && mv.fromTier && mv.toTier ? (
              <span className="inline-flex items-center gap-1.5">
                <RiskBadge risk={mv.fromTier} /> <ArrowRight className="size-3" /> <RiskBadge risk={mv.toTier} />
              </span>
            ) : (
              <RiskBadge risk={mv.tier} />
            )}
            · requested by {mv.requestedBy}
          </div>
        </div>
      </Section>
      <Section title="What changes on approval">
        <p className="text-sm text-muted-foreground">
          {mv.scope === 'tier_change'
            ? `The tier becomes ${mv.toTier}, which sets the publish gate and the injection threshold for everything it covers.`
            : 'The entry becomes validated (with conditions, if you add any) and its next review is set: 6 months for high and critical, 12 months otherwise.'}
        </p>
      </Section>
      <Section title={`Evidence · ${mv.evidence.length}`}>
        <ul className="flex flex-col gap-1.5 rounded-lg border p-3 text-sm">
          {mv.evidence.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      </Section>
      {mv.outcome && (
        <Section title="Decision">
          <div className="rounded-lg border bg-muted/40 p-3 text-sm">
            <p className="font-medium">{mv.outcome === 'approved' ? 'Approved' : mv.outcome === 'approved_with_conditions' ? 'Approved with conditions' : 'Rejected'}</p>
            {review.decisionReason && <p className="mt-1 text-muted-foreground">{review.decisionReason}</p>}
            {!!mv.conditions?.length && (
              <ul className="mt-2 list-disc pl-4 text-muted-foreground">
                {mv.conditions.map((c) => (
                  <li key={c.text}>
                    {c.text} · {c.owner} · due {c.dueDate}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Section>
      )}
      <p className="text-xs text-muted-foreground">
        <Link href={`/model-risk/${mv.entryId}`} className="underline underline-offset-2">
          Open {mv.entryName} in the model inventory
        </Link>
      </p>
    </div>
  );
}

/** What to do about the blockers that are actually present, worded from their causes. */
function blockerAdvice(pins: AgentEvalPin[], tier: Risk) {
  const kinds = new Set(pins.map((p) => p.blockerKind).filter(Boolean));
  const out: string[] = [];
  if (kinds.has('injection')) out.push('Injection failures block at every tier and cannot be overridden.');
  if (kinds.has('failing')) out.push(`At model tier ${tier}, every agent eval case must pass; this cannot be approved with a reason.`);
  if (kinds.has('running')) out.push('Wait for the running evals to finish.');
  if (kinds.has('no_run')) out.push('Run the agent’s evals.');
  if (kinds.has('injection') || kinds.has('failing')) out.push('Fix the agent and save it; evals re-run on save.');
  return out.join(' ');
}

/**
 * The tests and model-risk part of a publish request. The workflow's own test suite and each pinned agent's evals are
 * different suites, so they are shown as separate labelled rows; the gate's blockers are stated once, below them.
 */
export function PublishEvalSection({ review, validation }: { review: Review; validation: ValidationSummary | null }) {
  const p = review.publish!;
  const gate = p.evalGate;
  const pins = p.agentEvals ?? [];
  return (
    <>
      <Section title="Tests">
        <ul className="divide-y rounded-lg border text-sm" data-testid="publish-agent-evals">
          <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5" data-testid="publish-workflow-suite">
            <span className="w-full text-xs text-muted-foreground sm:w-40">Workflow test suite</span>
            {validation ? (
              <span className="flex flex-wrap items-center gap-x-3 text-xs tabular-nums text-muted-foreground">
                <span className="font-medium text-foreground">
                  {validation.passed}/{validation.total} passed
                </span>
                <span className={validation.regressions ? 'text-red-600 dark:text-red-400' : undefined}>{plural(validation.regressions, 'regression')} vs live</span>
                <span className={validation.checksFailing ? 'text-amber-700 dark:text-amber-400' : undefined}>{plural(validation.checksFailing, 'check')} failing</span>
              </span>
            ) : (
              <span className="text-xs text-muted-foreground">Requested without running the suite</span>
            )}
            <span className="ml-auto text-xs text-muted-foreground">Advisory</span>
          </li>
          {pins.map((a) => (
            <li key={a.agentId} className="flex flex-col gap-1 px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="w-full text-xs text-muted-foreground sm:w-40">
                  Agent evals ·{' '}
                  <Link href={`/agents/${a.agentId}?tab=evals`} className="font-medium text-foreground underline-offset-2 hover:underline">
                    {a.agentName}
                  </Link>{' '}
                  v{a.version}
                </span>
                {a.summary ? <EvalSummaryLine summary={a.summary} /> : <span className="text-xs text-muted-foreground">{a.blockerKind === 'running' ? 'Running' : 'Not run'}</span>}
                <span className={cn('ml-auto text-xs', a.blocker ? 'font-medium text-red-600 dark:text-red-400' : a.advisory.length ? 'text-amber-700 dark:text-amber-400' : 'text-muted-foreground')}>
                  {a.blocker ? 'Blocks publishing' : a.advisory.length ? 'Needs a reason' : 'Passes'}
                </span>
              </div>
              {a.advisory.map((x) => (
                <p key={x} className="text-xs text-amber-700 dark:text-amber-400">
                  {x}
                </p>
              ))}
            </li>
          ))}
        </ul>
        {gate && gate.reasonRequired && !gate.blockers.length && (
          <p className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> Failing agent evals are advisory at model tier {gate.tier}. Approving needs a written reason, which goes into the evidence bundle.
          </p>
        )}
      </Section>
      {gate && gate.blockers.length > 0 && (
        <Alert variant="destructive" data-testid="publish-eval-blocked">
          <ShieldAlert />
          <AlertTitle>Publishing is blocked</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {gate.blockers.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
            <p className="mt-1">{blockerAdvice(pins, gate.tier)}</p>
          </AlertDescription>
        </Alert>
      )}
      {p.modelEntry && (
        <Section title="Model risk">
          {p.modelEntry.needsValidation ? (
            <Alert data-testid="publish-model-not-validated">
              <ShieldAlert />
              <AlertTitle>
                {review.workflowName} is {VALIDATION_STATUS_LABEL[p.modelEntry.validationStatus].toLowerCase()}
              </AlertTitle>
              <AlertDescription>
                <span>
                  Its model tier is {p.modelEntry.tier}. Model Risk has not validated it, so approving publishes a version no second line has reviewed.{' '}
                  <Link href={`/model-risk/${p.modelEntry.entryId}`} className="underline underline-offset-2">
                    Open its inventory entry
                  </Link>
                </span>
              </AlertDescription>
            </Alert>
          ) : (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <ShieldCheck className="size-4" /> Model tier <RiskBadge risk={p.modelEntry.tier} /> {VALIDATION_STATUS_LABEL[p.modelEntry.validationStatus]}
              <Link href={`/model-risk/${p.modelEntry.entryId}`} className="ml-auto text-xs underline underline-offset-2">
                Inventory entry
              </Link>
            </p>
          )}
        </Section>
      )}
    </>
  );
}

const in90Days = () => new Date(Date.now() + 90 * 86_400_000).toISOString().slice(0, 10);

/**
 * Decision form for a model validation. Only Model Risk decides: the current user holds that role in the mock,
 * and choosing anyone else under "Deciding as" shows who may not decide. Approving can attach conditions.
 */
export function ModelValidationDecisionForm({
  review,
  currentUser,
  owners,
  principals,
  principalsLoading,
  pending,
  onDecide,
}: {
  review: Review;
  currentUser?: string;
  owners: string[];
  principals: RunAsPrincipal[];
  principalsLoading: boolean;
  pending: ReviewDecision | null;
  onDecide: (decision: ReviewDecision, reason: string, conditions: ConditionInput[], actingAsId?: string) => void;
}) {
  const [reason, setReason] = React.useState('');
  const [missing, setMissing] = React.useState<string | null>(null);
  const [conditions, setConditions] = React.useState<ConditionInput[]>([]);
  const [actingAs, setActingAs] = React.useState<string | null>(null);
  const [conditionErrors, setConditionErrors] = React.useState<Record<number, string>>({});
  React.useEffect(() => {
    setReason('');
    setMissing(null);
    setConditionErrors({});
    setConditions([]);
    setActingAs(null);
  }, [review.id]);

  const mv = review.modelValidation!;
  const acting = principals.find((p) => p.id === actingAs);
  const ownRequest = !acting && !!currentUser && mv.requestedBy === currentUser;
  const locked = !!acting || ownRequest;
  const conditionProblem = (c: ConditionInput) => (!c.text.trim() ? 'Describe the condition.' : !c.owner ? 'Choose who owns it.' : !c.dueDate ? 'Pick a due date.' : null);
  const submit = (decision: ReviewDecision) => {
    if (decision !== 'approved' && !reason.trim()) return setMissing('Add a reason before rejecting or returning.');
    if (decision === 'approved') {
      const errs = Object.fromEntries(conditions.flatMap((c, i) => (conditionProblem(c) ? [[i, conditionProblem(c)!]] : [])));
      setConditionErrors(errs);
      if (Object.keys(errs).length) return;
    }
    setMissing(null);
    onDecide(decision, reason.trim(), conditions, actingAs ?? undefined);
  };
  const editCondition = (i: number, patch: Partial<ConditionInput>) => {
    setConditions((cs) => cs.map((x, j) => (j === i ? { ...x, ...patch } : x)));
    setConditionErrors(({ [i]: _, ...rest }) => rest);
  };

  // Who decides and the conditions live in the scrolling body; the sticky footer holds only the reason and buttons,
  // so it stays short however many conditions are added.
  return (
    <>
      <div className="flex flex-col gap-4 border-t pt-4" data-testid="model-validation-setup">
        <div className="flex flex-col gap-1.5">
          <Label>Deciding as</Label>
          <RunAsBar principals={principals} loading={principalsLoading} value={actingAs} onChange={setActingAs} className="shadow-none" />
          {acting ? (
            <p className="text-xs text-destructive" data-testid="only-model-risk">
              Only Model Risk can decide. {acting.name} ({acting.title}) cannot approve or reject validations.
            </p>
          ) : ownRequest ? (
            <p className="text-xs text-muted-foreground">You requested this. Another Model Risk validator must decide it.</p>
          ) : (
            <p className="text-xs text-muted-foreground">You hold the Model Risk role.</p>
          )}
        </div>
        {mv.scope !== 'tier_change' && (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <Label>
                Conditions <span className="font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Button variant="ghost" size="sm" disabled={locked} onClick={() => setConditions((c) => [...c, { text: '', owner: '', dueDate: in90Days() }])}>
                <Plus className="size-3.5" /> Add condition
              </Button>
            </div>
            {!conditions.length && <p className="text-xs text-muted-foreground">Approve as is, or add conditions the owner must meet by a date.</p>}
            {conditions.map((c, i) => (
              <div key={i} className="flex flex-col gap-1">
                <div className="grid grid-cols-1 gap-2 rounded-md border p-2 sm:grid-cols-[minmax(0,1fr)_10rem_9rem_auto]" data-testid="condition-row" aria-invalid={!!conditionErrors[i]}>
                  <Input aria-label="Condition" aria-invalid={!!conditionErrors[i] && !c.text.trim()} value={c.text} onChange={(e) => editCondition(i, { text: e.target.value })} placeholder="e.g. Human approval on all writes until 31 Dec" />
                  <Select value={c.owner} onValueChange={(owner) => editCondition(i, { owner })}>
                    <SelectTrigger aria-label="Owner" className="w-full" aria-invalid={!!conditionErrors[i] && !!c.text.trim() && !c.owner}>
                      <SelectValue placeholder="Owner" />
                    </SelectTrigger>
                    <SelectContent>
                      {owners.map((o) => (
                        <SelectItem key={o} value={o}>
                          {o}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input aria-label="Due date" type="date" value={c.dueDate} onChange={(e) => editCondition(i, { dueDate: e.target.value })} />
                  <Button variant="ghost" size="icon" aria-label="Remove condition" onClick={() => (setConditions((cs) => cs.filter((_, j) => j !== i)), setConditionErrors({}))}>
                    <X className="size-4" />
                  </Button>
                </div>
                {conditionErrors[i] && (
                  <p className="text-xs text-destructive" data-testid="condition-error">
                    {conditionErrors[i]}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="sticky bottom-0 -mx-6 -mb-4 flex flex-col gap-2 border-t bg-background px-6 py-3 shadow-[0_-4px_12px_-8px_rgb(0_0_0/0.15)]" data-testid="model-validation-decision-form">
        <Label htmlFor="validation-reason" className="sr-only">
          Reason
        </Label>
        <Textarea id="validation-reason" rows={1} value={reason} onChange={(e) => (setReason(e.target.value), setMissing(null))} aria-invalid={!!missing} placeholder="e.g. Evidence covers the injection set; attachment parsing still untested" className="min-h-9 resize-none bg-card" />
        <p className={cn('text-xs', missing ? 'text-destructive' : 'text-muted-foreground')}>{missing ?? 'Reason: required to reject or return.'}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" disabled={!!pending || locked} onClick={() => submit('returned')}>
            Return to requester
          </Button>
          <div className="ml-auto flex gap-2">
            <LoadingButton variant="outline" size="sm" isLoading={pending === 'rejected'} disabled={!!pending || locked} onClick={() => submit('rejected')}>
              Reject
            </LoadingButton>
            <LoadingButton size="sm" isLoading={pending === 'approved'} disabled={!!pending || locked} onClick={() => submit('approved')} data-testid="approve-validation">
              {acting ? 'Only Model Risk can decide' : mv.scope === 'tier_change' ? `Approve ${mv.toTier} tier` : conditions.length ? `Approve with ${plural(conditions.length, 'condition')}` : 'Approve'}
            </LoadingButton>
          </div>
        </div>
      </div>
    </>
  );
}
