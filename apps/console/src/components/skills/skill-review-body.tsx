'use client';

import Link from 'next/link';
import { Bot, CheckCircle2, ShieldCheck, XCircle } from 'lucide-react';

import { FieldSectionLabel } from '@/components/shared/field-row';
import { Badge } from '@/components/ui/badge';
import { plural, relativeTime } from '@/lib/format';
import type { Review } from '@/lib/types/domain';

import { EDIT_CLASS, EditClassBadge } from './skill-meta';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <FieldSectionLabel>{title}</FieldSectionLabel>
      {children}
    </section>
  );
}

/** Read-only body of a `skill_publish` review: what changes, the test result, and which agents pin it. */
export function SkillPublishBody({ review }: { review: Review }) {
  const p = review.skillPublish!;
  const open = review.status === 'pending' || review.status === 'in_review';
  const run = p.testRun;
  return (
    <div className="flex flex-col gap-6" data-testid="skill-publish-body">
      <Section title="Skill publish request">
        <div className="rounded-lg border border-primary/25 bg-primary/5 p-4">
          <p className="text-sm font-medium">{p.note}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            {p.skillName} · {p.fromVersion ? `v${p.fromVersion} → ` : 'first version, '}v{p.toVersion} · {p.ownerTeam} · requested by {p.requestedBy}
          </p>
        </div>
      </Section>
      <Section title="Edit class">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <EditClassBadge editClass={p.editClass} />
          <span className="text-muted-foreground">{EDIT_CLASS[p.editClass].hint}</span>
        </div>
        <p className="flex items-center gap-1.5 text-sm">
          <ShieldCheck className="size-4 text-muted-foreground" /> {review.approvals.length} of {plural(p.approvalsNeeded, 'approval')}
          {review.approvals.length > 0 && <span className="text-muted-foreground">· approved by {review.approvals.join(', ')}</span>}
        </p>
      </Section>
      <Section title={`Changes · ${p.changes.length}`}>
        <ul className="flex flex-col gap-1.5 rounded-lg border p-3 text-sm">
          {p.changes.map((c) => (
            <li key={c}>{c}</li>
          ))}
          {p.toolsAdded.length > 0 && <li>Adds tools: {p.toolsAdded.join(', ')}</li>}
          {p.kbsAdded.length > 0 && <li>Adds knowledge bases: {p.kbsAdded.join(', ')}</li>}
        </ul>
        {p.guardrails.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {p.guardrails.map((g) => (
              <Badge key={g} variant="secondary" className="font-normal">
                {g}
              </Badge>
            ))}
          </div>
        )}
      </Section>
      <Section title="Tests">
        {run ? (
          <div className="flex flex-col gap-1.5 rounded-lg border p-3 text-sm" data-testid="skill-publish-tests">
            <span className={run.passed === run.total ? 'flex items-center gap-1.5 font-medium text-success-text' : 'flex items-center gap-1.5 font-medium text-warning-text'}>
              {run.passed === run.total ? <CheckCircle2 className="size-4" /> : <XCircle className="size-4" />}
              {run.passed} of {plural(run.total, 'case')} pass on v{run.version} · {relativeTime(run.ranAt)}
            </span>
            {p.failing.length > 0 && <span className="text-xs text-muted-foreground">Failing: {p.failing.join(', ')}. Approving needs a reason, which is kept with the version.</span>}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No test run on this version.</p>
        )}
      </Section>
      <Section title={`Agents · ${p.agents.length}`}>
        {p.agents.length ? (
          <ul className="divide-y rounded-lg border text-sm">
            {p.agents.map((a) => (
              <li key={a.name} className="flex items-center gap-2 px-3 py-2">
                <Bot className="size-3.5 text-muted-foreground" /> {a.name}
                <span className="ml-auto text-xs text-muted-foreground">{a.pinnedVersion ? `pins v${a.pinnedVersion}; keeps it until moved` : 'Target; not attached yet'}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No agent uses it yet.</p>
        )}
      </Section>
      {!open && review.decisionReason && (
        <Section title="Decision">
          <p className="rounded-lg border bg-muted/40 p-3 text-sm">{review.decisionReason}</p>
        </Section>
      )}
      <p className="text-xs text-muted-foreground">
        Approving publishes v{p.toVersion}. No agent moves to it until its owner moves the pin.{' '}
        <Link href={`/skills/${p.skillId}?tab=versions`} className="underline underline-offset-2">
          Open the skill’s versions
        </Link>
      </p>
    </div>
  );
}
