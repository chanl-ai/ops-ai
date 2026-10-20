'use client';

import Link from 'next/link';
import { AlertTriangle } from 'lucide-react';

import { PromptDiff } from '@/components/prompts/prompt-diff';
import { FieldSectionLabel } from '@/components/shared/field-row';
import { AccessBadge, RiskBadge } from '@/components/status-badges';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { Review } from '@/lib/types/domain';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <FieldSectionLabel>{title}</FieldSectionLabel>
      {children}
    </section>
  );
}

const UNSURE = { handoff: 'Hand to a person', ask: 'Ask the customer to clarify', decline: 'Decline and explain why' } as const;

/** Read-only body of a `template_submission` review: what the template would offer every team, and how it differs from its agent. */
export function TemplateSubmissionBody({ review }: { review: Review }) {
  const ts = review.templateSubmission!;
  const c = ts.content;
  const open = review.status === 'pending' || review.status === 'in_review';
  return (
    <div className="flex flex-col gap-6" data-testid="template-submission-body">
      <Section title="Template submission">
        <div className="rounded-lg border border-primary/25 bg-primary/5 p-4">
          <p className="text-sm font-medium">{ts.templateName}</p>
          <p className="mt-1 text-sm text-muted-foreground">{ts.summary}</p>
          {ts.note && <p className="mt-2 text-sm">“{ts.note}”</p>}
          <p className="mt-2 text-xs text-muted-foreground">
            {ts.category} · from{' '}
            <Link href={`/agents/${ts.sourceAgentId}`} className="underline underline-offset-2">
              {ts.sourceAgentName} v{ts.sourceVersion}
            </Link>{' '}
            · {ts.submittedTeam} · submitted by {ts.submittedBy}
          </p>
        </div>
        {ts.agentVersionNow !== ts.sourceVersion && (
          <p className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-2.5 text-xs text-warning-text" role="status">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
            {ts.sourceAgentName} is now at v{ts.agentVersionNow}. The template copies v{ts.sourceVersion}; later changes are not included.
          </p>
        )}
      </Section>

      <Section title="Against the source agent">
        <div className="rounded-lg border">
          <Table data-testid="template-diff">
            <TableHeader>
              <TableRow>
                <TableHead>Field</TableHead>
                <TableHead>{ts.sourceAgentName}</TableHead>
                <TableHead>Template</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {ts.diff.map((d) => (
                <TableRow key={d.field} className="align-top">
                  <TableCell className="text-muted-foreground">{d.field}</TableCell>
                  <TableCell className="whitespace-normal">{d.agent}</TableCell>
                  <TableCell className="whitespace-normal">{d.template}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {ts.agentInstructionsNow !== undefined && (
          <div className="flex flex-col gap-1.5">
            <p className="text-xs text-muted-foreground">Instructions on the agent now, against the copied ones</p>
            <PromptDiff before={c.instructions} after={ts.agentInstructionsNow} />
          </div>
        )}
      </Section>

      <Section title="Template preview">
        <div className="flex flex-col gap-3 rounded-lg border p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">Risk tier</span> <RiskBadge risk={ts.riskTier} />
            <span className="text-muted-foreground">· model</span> <code className="font-mono">{c.model}</code>
            <span className="text-muted-foreground">· channels</span> {c.channels.join(', ')}
          </div>
          <p>{c.role}</p>
          <div className="flex flex-col gap-1">
            <p className="text-xs font-medium text-muted-foreground">Tools it expects</p>
            {c.expectedTools.length ? (
              <ul className="flex flex-wrap gap-1.5">
                {c.expectedTools.map((t) => (
                  <li key={t.name} className="flex items-center gap-1.5 text-xs">
                    <code className="font-mono">{t.name}</code> <AccessBadge access={t.access} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground">None</p>
            )}
          </div>
          <div className="flex flex-col gap-1">
            <p className="text-xs font-medium text-muted-foreground">Knowledge it expects</p>
            <p className="text-xs">{c.expectedKnowledge.join(', ') || 'None'}</p>
          </div>
          <div className="flex flex-col gap-1">
            <p className="text-xs font-medium text-muted-foreground">Skills it suggests</p>
            <p className="text-xs">{c.suggestedSkills.map((s) => s.name).join(', ') || 'None'}</p>
          </div>
          <div className="flex flex-col gap-1">
            <p className="text-xs font-medium text-muted-foreground">Guardrails</p>
            <p className="text-xs">
              {UNSURE[c.guardrails.whenUnsure]} when unsure · at most {c.guardrails.maxToolCallsPerTurn} tool calls per turn · personal data {c.guardrails.redactPii ? 'redacted' : 'not redacted'}
              {c.guardrails.blockedTopics.length > 0 && ` · blocks ${c.guardrails.blockedTopics.join(', ')}`}
            </p>
          </div>
          <div className="flex flex-col gap-1">
            <p className="text-xs font-medium text-muted-foreground">Instructions</p>
            <pre className="max-h-64 overflow-auto rounded-md border bg-muted/30 p-2.5 font-mono text-xs leading-relaxed whitespace-pre-wrap">{c.instructions || 'None'}</pre>
          </div>
        </div>
      </Section>

      {!open && review.decisionReason && (
        <Section title="Decision">
          <p className="rounded-lg border bg-muted/40 p-3 text-sm">{review.decisionReason}</p>
        </Section>
      )}
      <p className="text-xs text-muted-foreground">Approving publishes the template to every team’s gallery. Agents already made from {ts.sourceAgentName} do not change. The platform team decides; the submitter cannot approve.</p>
    </div>
  );
}
