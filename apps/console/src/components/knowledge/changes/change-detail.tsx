'use client';

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle, BookOpen, CheckCircle2, FlaskConical, Route, XCircle } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { count, dateTime, plural } from '@/lib/format';
import type { KnowledgeChange } from '@/lib/types/knowledge-changes';

import { PassageDiff } from './diff';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h3>
      {children}
    </section>
  );
}

/** What changed, why, what it disagrees with, and which workflows depend on it. */
export function ChangeDetailBody({ change: c }: { change: KnowledgeChange }) {
  const docHref = c.kbs[0] ? `/knowledge/${c.kbs[0].id}?tab=documents&doc=${c.documentId}` : undefined;
  return (
    <div className="flex flex-col gap-6">
      <Section title="Why">
        <p className="text-sm">{c.rationale}</p>
        <p className="text-xs text-muted-foreground">
          Proposed by {c.proposedBy} · {dateTime(c.createdAt)}
        </p>
      </Section>

      <Section title="Change">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <BookOpen className="size-4 text-muted-foreground" />
          {docHref ? (
            <Link href={docHref} className="font-medium hover:underline">
              {c.documentTitle}
            </Link>
          ) : (
            <span className="font-medium">{c.documentTitle}</span>
          )}
          <span className="text-muted-foreground">· {c.section}</span>
          <Badge variant="outline" className="font-mono font-normal">
            {c.fromVersion} → {c.toVersion}
          </Badge>
        </div>
        <PassageDiff before={c.before} after={c.after} />
        <p className="text-xs text-muted-foreground">
          {c.sourceName} · in {c.kbs.map((k) => k.name).join(', ') || 'no knowledge base'}
        </p>
      </Section>

      {c.conflict && (
        <Section title="Conflict">
          {c.conflict.resolution ? (
            <Alert>
              <CheckCircle2 />
              <AlertTitle>Resolved</AlertTitle>
              <AlertDescription>
                {c.conflict.resolution === 'supersede_other'
                  ? `${c.conflict.documentTitle} is marked superseded once this change is approved.`
                  : `Both are kept; agents follow this change where they disagree with ${c.conflict.documentTitle}.`}
              </AlertDescription>
            </Alert>
          ) : (
            <Alert variant="destructive" data-testid="change-conflict">
              <AlertTriangle />
              <AlertTitle>Disagrees with {c.conflict.documentTitle}</AlertTitle>
              <AlertDescription>
                {c.conflict.sourceName}: “{c.conflict.passage}”
              </AlertDescription>
            </Alert>
          )}
        </Section>
      )}

      <Section title="Cited by">
        {c.citedBy.length ? (
          <ul className="divide-y rounded-md border">
            {c.citedBy.map((w) => (
              <li key={w.workflowId} className="flex items-center gap-3 px-3 py-2 text-sm">
                <Route className="size-4 shrink-0 text-muted-foreground" />
                <Link href={`/workflows/${w.workflowId}?tab=tests`} className="min-w-0 flex-1 truncate hover:underline">
                  {w.workflowName}
                </Link>
                <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">
                  {count(w.citations30d)} citations · 30 days
                </span>
                <Badge variant="secondary" className="font-normal whitespace-nowrap tabular-nums">
                  <FlaskConical className="size-3" /> {plural(w.tests, 'test')}
                </Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No workflow has cited this passage in the last 30 days.</p>
        )}
      </Section>

      {c.status !== 'pending' && (
        <Section title="Decision">
          <div className="flex items-start gap-2 text-sm">
            {c.status === 'approved' ? <CheckCircle2 className="mt-0.5 size-4 text-success-text" /> : <XCircle className="mt-0.5 size-4 text-destructive" />}
            <div>
              <div>
                {c.status === 'approved' ? 'Approved' : 'Rejected'} by {c.decidedBy} · {dateTime(c.decidedAt)}
              </div>
              {c.decisionReason && <p className="text-muted-foreground">“{c.decisionReason}”</p>}
              {c.retest && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Re-ran {plural(c.retest.tests, 'test')} in {c.retest.workflows.join(', ')}.
                </p>
              )}
            </div>
          </div>
        </Section>
      )}
    </div>
  );
}
