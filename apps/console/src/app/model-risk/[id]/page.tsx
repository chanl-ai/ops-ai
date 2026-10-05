'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Activity, AlertTriangle, Bot, ClipboardCheck, FileCheck2, Gauge, ListChecks, Plus, Route, Scale, SearchX, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';

import { EvalSummaryLine } from '@/components/evals/eval-meta';
import { ConditionDialog, ConditionStatusDialog, NextReviewDialog, RequestValidationDialog, TierDialog } from '@/components/model-risk/model-risk-dialogs';
import { ConditionBadge, FINDING_STATUS_LABEL, SeverityBadge, TYPE_LABEL, ValidationBadge } from '@/components/model-risk/model-risk-meta';
import { OverrideRateChart, PassRateChart } from '@/components/model-risk/monitoring-charts';
import { PageLayout } from '@/components/page-layout';
import { toastBulk } from '@/components/shared/bulk';
import { EmptyState } from '@/components/shared/empty-state';
import { FieldRow } from '@/components/shared/field-row';
import { DisabledReason } from '@/components/shared/disabled-reason';
import { QueryError } from '@/components/shared/query-states';
import { AttributeCard, RecordLayout } from '@/components/shared/record-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { RiskBadge } from '@/components/status-badges';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useLookups } from '@/hooks/queries';
import { useAddCondition, useChangeTier, useModelEntry, useRequestValidation, useSetConditionStatus, useSetNextReview } from '@/hooks/model-risk-queries';
import { ApiError } from '@/lib/api';
import { dateOnly, pct, relativeTime, shortDate, shortId } from '@/lib/format';
import type { ModelCondition, ModelEntryDetail } from '@/lib/types/model-risk';

const OUTCOME_LABEL = { approved: 'Approved', approved_with_conditions: 'Approved with conditions', rejected: 'Rejected' } as const;

function Section({ title, description, icon: Icon, action, children, testId }: { title: string; description?: string; icon: React.ComponentType<{ className?: string }>; action?: React.ReactNode; children: React.ReactNode; testId?: string }) {
  return (
    <Card className="gap-3" data-testid={testId}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base font-medium">
          <Icon className="size-4 text-muted-foreground" /> {title}
        </CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export default function ModelEntryPage() {
  const { id } = useParams<{ id: string }>();
  const query = useModelEntry(id);
  if (query.isPending) return <RecordSkeleton />;
  if (query.isError)
    return (
      <PageLayout icon={Scale} title="Model" backHref="/model-risk">
        {query.error instanceof ApiError && query.error.status === 404 ? (
          <EmptyState icon={SearchX} title="Model not found" description="It may have been deleted, or the link is wrong." action={{ label: 'Back to model risk', href: '/model-risk' }} />
        ) : (
          <QueryError what="this model" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
        )}
      </PageLayout>
    );
  return <ModelEntryView entry={query.data} />;
}

function ModelEntryView({ entry: e }: { entry: ModelEntryDetail }) {
  const { data: lookups } = useLookups();
  const changeTier = useChangeTier(e.id);
  const addCondition = useAddCondition(e.id);
  const setConditionStatus = useSetConditionStatus(e.id);
  const request = useRequestValidation();
  const nextReview = useSetNextReview();
  const [dialog, setDialog] = React.useState<'tier' | 'condition' | 'validate' | 'review' | null>(null);
  const [conditionTarget, setConditionTarget] = React.useState<ModelCondition | null>(null);
  const Icon = e.type === 'agent' ? Bot : Route;
  const openConditions = e.conditions.filter((c) => c.status !== 'met');

  return (
    <PageLayout
      icon={Icon}
      backHref="/model-risk"
      title={e.name}
      description={e.purpose}
      badge={
        <>
          <RiskBadge risk={e.tier} />
          <ValidationBadge status={e.validationStatus} />
          <span className="text-xs text-muted-foreground">
            {TYPE_LABEL[e.type]} · {e.ownerTeam} · next review {e.nextReviewAt ? dateOnly(e.nextReviewAt) : 'not set'}
          </span>
        </>
      }
      actions={
        <>
          <DisabledReason reason={e.pendingReview?.scope === 'tier_change' ? `A tier change is already waiting for Model Risk (${e.pendingReview.id}).` : undefined}>
            <Button variant="outline" onClick={() => setDialog('tier')} disabled={e.pendingReview?.scope === 'tier_change'} data-testid="change-tier-button">
              <Gauge className="size-4" /> Change tier
            </Button>
          </DisabledReason>
          <Button variant="outline" onClick={() => setDialog('condition')}>
            <Plus className="size-4" /> Add condition
          </Button>
          <DisabledReason reason={e.pendingReview ? `${e.pendingReview.scope === 'tier_change' ? 'A tier change' : 'A validation'} is already open with Model Risk (${e.pendingReview.id}). Decide it first.` : undefined}>
            <Button onClick={() => setDialog('validate')} disabled={!!e.pendingReview}>
              <ClipboardCheck className="size-4" /> Request validation
            </Button>
          </DisabledReason>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {e.pendingReview && (
          <Alert>
            <ShieldCheck />
            <AlertTitle>{e.pendingReview.scope === 'tier_change' ? `A change to ${e.pendingReview.toTier} tier is waiting for Model Risk` : 'Validation is in progress with Model Risk'}</AlertTitle>
            <AlertDescription>
              <Link href={`/reviews?review=${e.pendingReview.id}`} className="underline underline-offset-2">
                Open review {e.pendingReview.id}
              </Link>
            </AlertDescription>
          </Alert>
        )}
        <RecordLayout
          rail={
            <>
              <AttributeCard title="Attributes" icon={Scale}>
                <FieldRow label="Type" value={TYPE_LABEL[e.type]} href={e.href} />
                <FieldRow label="Owner" value={e.owner} />
                <FieldRow label="Team" value={e.ownerTeam} />
                <FieldRow label="Model" value={e.model} mono />
                <FieldRow label="Alias" value={`${e.alias} · ${e.provider}`} mono />
                <FieldRow label="Next review" value={e.nextReviewAt ? dateOnly(e.nextReviewAt) : undefined} onEdit={() => setDialog('review')} />
              </AttributeCard>
              <AttributeCard title="Risk tier" icon={Gauge} action={<Button variant="ghost" size="sm" className="h-7" onClick={() => setDialog('tier')} disabled={e.pendingReview?.scope === 'tier_change'}>Change</Button>}>
                <div className="flex flex-col gap-2 text-sm">
                  <RiskBadge risk={e.tier} />
                  <p className="text-muted-foreground">{e.tierReason}</p>
                </div>
              </AttributeCard>
              <AttributeCard title="What it touches" icon={Activity}>
                <div className="flex flex-col gap-3 text-sm">
                  {[
                    { label: 'Data', items: e.dataTouched },
                    { label: 'Systems', items: e.systems },
                    { label: 'Knowledge bases', items: e.knowledgeBases },
                  ].map((g) => (
                    <div key={g.label}>
                      <div className="mb-1 text-xs text-muted-foreground">{g.label}</div>
                      {g.items.length ? (
                        <div className="flex flex-wrap gap-1">
                          {g.items.map((x) => (
                            <Badge key={x} variant="secondary" className="font-normal">
                              {x}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <span className="text-muted-foreground">None</span>
                      )}
                    </div>
                  ))}
                </div>
              </AttributeCard>
            </>
          }
        >
          <div className="flex flex-col gap-4">
            <Section title="Evidence" icon={FileCheck2} description="Latest evals for the version in use, the workflow's test run, and the sealed evidence bundle per version." testId="model-evidence">
              <div className="flex flex-col gap-4">
                {e.evidence.evals.length ? (
                  <ul className="divide-y rounded-md border">
                    {e.evidence.evals.map((x) => (
                      <li key={x.name} className="flex flex-wrap items-center gap-2 px-3 py-2">
                        <span className="text-sm font-medium">{x.name}</span>
                        <span className="font-mono text-xs text-muted-foreground">v{x.version}</span>
                        <EvalSummaryLine summary={x.summary} className="ml-auto" />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">No eval has run on the version in use.</p>
                )}
                {e.type === 'workflow' && (
                  <p className="text-sm">
                    <span className="text-muted-foreground">Workflow test suite: </span>
                    {e.evidence.workflowSuite ? (
                      <>
                        {e.evidence.workflowSuite.passed}/{e.evidence.workflowSuite.total} passed · {e.evidence.workflowSuite.regressions} regressions · {relativeTime(e.evidence.workflowSuite.ranAt)}
                      </>
                    ) : (
                      'not run in this session'
                    )}
                  </p>
                )}
                <div className="overflow-hidden rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Version</TableHead>
                        <TableHead>Evidence bundle</TableHead>
                        <TableHead>Sealed</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {e.evidence.bundles.map((b) => (
                        <TableRow key={b.version}>
                          <TableCell className="font-mono text-xs">v{b.version}</TableCell>
                          <TableCell className="font-mono text-xs" title={b.bundleId}>
                            {shortId(b.bundleId)}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">{shortDate(b.sealedAt)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>
            </Section>

            <Section title="Monitoring" icon={Activity} description="Eval pass rate per version, and how often approvers changed or rejected what it proposed." testId="model-monitoring">
              <div className="grid gap-4 xl:grid-cols-2">
                <div>
                  <div className="mb-1 text-xs font-medium text-muted-foreground">Eval pass rate by version</div>
                  <PassRateChart data={e.monitoring.passRateByVersion} />
                </div>
                <div>
                  <div className="mb-1 text-xs font-medium text-muted-foreground">Approver override rate · 30 days</div>
                  <OverrideRateChart data={e.monitoring.overrideRate30d} />
                </div>
              </div>
            </Section>

            <Section title={`Conditions · ${openConditions.length} open`} icon={ListChecks} action={<Button variant="outline" size="sm" onClick={() => setDialog('condition')}><Plus className="size-3.5" /> Add condition</Button>} testId="model-conditions">
              {e.conditions.length ? (
                <div className="overflow-x-auto rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Condition</TableHead>
                        <TableHead>Owner</TableHead>
                        <TableHead>Due</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className="w-28" />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {e.conditions.map((c) => (
                        <TableRow key={c.id}>
                          <TableCell className="max-w-96 whitespace-normal">{c.text}</TableCell>
                          <TableCell className="whitespace-nowrap text-xs">{c.owner}</TableCell>
                          <TableCell className="whitespace-nowrap text-xs tabular-nums">{dateOnly(c.dueDate)}</TableCell>
                          <TableCell>
                            <ConditionBadge status={c.status} />
                          </TableCell>
                          <TableCell className="text-right">
                            <Button variant="ghost" size="sm" onClick={() => setConditionTarget(c)}>
                              {c.status === 'met' ? 'Reopen' : 'Mark met'}
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No conditions. Model Risk adds them when it approves with conditions, or you can add one.</p>
              )}
            </Section>

            <Section title="Validation history" icon={ShieldCheck} testId="model-validations">
              {e.validations.length ? (
                <ol className="relative flex flex-col gap-3 border-l pl-5">
                  {e.validations.map((v) => (
                    <li key={v.id} className="relative">
                      <span className={`absolute top-1.5 -left-[25px] size-2.5 rounded-full border-2 border-background ${v.outcome === 'rejected' ? 'bg-red-500' : 'bg-emerald-500'}`} />
                      <div className="text-sm font-medium">
                        {OUTCOME_LABEL[v.outcome]} <span className="font-normal text-muted-foreground">· {v.validator} · {shortDate(v.date)}</span>
                      </div>
                      {v.reason && <p className="text-sm text-muted-foreground">{v.reason}</p>}
                      {v.conditions.length > 0 && (
                        <ul className="mt-1 list-disc pl-4 text-xs text-muted-foreground">
                          {v.conditions.map((c) => (
                            <li key={c}>{c}</li>
                          ))}
                        </ul>
                      )}
                      {v.reviewId && (
                        <Link href={`/reviews?review=${v.reviewId}`} className="text-xs underline underline-offset-2">
                          {v.reviewId}
                        </Link>
                      )}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-sm text-muted-foreground">Never validated. {e.tier !== 'low' ? `A ${e.tier} tier model should be validated by Model Risk before it reaches production.` : ''}</p>
              )}
            </Section>

            <Section title={`Findings · ${e.findings.filter((f) => f.status !== 'closed').length} open`} icon={AlertTriangle} testId="model-findings">
              {e.findings.length ? (
                <div className="overflow-x-auto rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Finding</TableHead>
                        <TableHead>Severity</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Raised</TableHead>
                        <TableHead>Due</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {e.findings.map((f) => (
                        <TableRow key={f.id}>
                          <TableCell className="max-w-96 whitespace-normal">{f.title}</TableCell>
                          <TableCell>
                            <SeverityBadge severity={f.severity} />
                          </TableCell>
                          <TableCell className="text-xs">{FINDING_STATUS_LABEL[f.status]}</TableCell>
                          <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                            {f.raisedBy} · {relativeTime(f.raisedAt)}
                          </TableCell>
                          <TableCell className="whitespace-nowrap text-xs tabular-nums">{f.dueDate ? dateOnly(f.dueDate) : '—'}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No findings.</p>
              )}
            </Section>
            {e.lastEvalPassRate !== null && <p className="text-xs text-muted-foreground">Last eval pass rate across the agents in use: {pct(e.lastEvalPassRate)}.</p>}
          </div>
        </RecordLayout>
      </div>

      <TierDialog
        open={dialog === 'tier'}
        onOpenChange={(o) => !o && setDialog(null)}
        name={e.name}
        current={e.tier}
        isPending={changeTier.isPending}
        onSubmit={async (tier, reason) => {
          const next = await changeTier.mutateAsync({ tier, reason });
          if (next.pendingReview?.scope === 'tier_change') toast.success(`Sent to Model Risk as ${next.pendingReview.id}`, { description: `${e.name} stays ${e.tier} until they approve.` });
          else toast.success(`${e.name} is now ${next.tier} tier`, { description: 'Recorded in the audit log.' });
        }}
      />
      <ConditionDialog
        open={dialog === 'condition'}
        onOpenChange={(o) => !o && setDialog(null)}
        owners={lookups?.owners ?? []}
        isPending={addCondition.isPending}
        onSubmit={async (c) => {
          await addCondition.mutateAsync(c);
          toast.success('Condition added', { description: 'Recorded in the audit log.' });
        }}
      />
      <ConditionStatusDialog
        open={!!conditionTarget}
        onOpenChange={(o) => !o && setConditionTarget(null)}
        text={conditionTarget?.text ?? ''}
        next={conditionTarget?.status === 'met' ? 'open' : 'met'}
        isPending={setConditionStatus.isPending}
        onSubmit={async (reason) => {
          if (!conditionTarget) return;
          const next = conditionTarget.status === 'met' ? 'open' : 'met';
          await setConditionStatus.mutateAsync({ conditionId: conditionTarget.id, status: next, reason });
          toast.success(next === 'met' ? 'Condition marked met' : 'Condition reopened');
        }}
      />
      <RequestValidationDialog
        open={dialog === 'validate'}
        onOpenChange={(o) => !o && setDialog(null)}
        names={[e.name]}
        isPending={request.isPending}
        onSubmit={async (note) => {
          const res = await request.mutateAsync({ ids: [e.id], note: note || undefined });
          toastBulk(res, 'Requested validation of', 'model', () => e.name);
        }}
      />
      <NextReviewDialog
        open={dialog === 'review'}
        onOpenChange={(o) => !o && setDialog(null)}
        names={[e.name]}
        isPending={nextReview.isPending}
        onSubmit={async (date) => {
          const res = await nextReview.mutateAsync({ ids: [e.id], date });
          toastBulk(res, 'Rescheduled', 'model', () => e.name);
        }}
      />
    </PageLayout>
  );
}
