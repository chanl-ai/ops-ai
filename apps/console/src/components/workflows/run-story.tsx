'use client';

import * as React from 'react';
import Link from 'next/link';
import { FileText } from 'lucide-react';

import { DocumentReadView, type ReadDocument } from '@/components/files/document-read-view';
import { FieldRow } from '@/components/shared/field-row';
import { Row, Rows, Section } from '@/components/shared/surface';
import { Button } from '@/components/ui/button';
import { RunStatus } from '@/components/workflows/run-journal/run-status';
import { bytes, dateTime, mimeLabel, plural, relativeTime } from '@/lib/format';
import type { RunEmail, RunRead, RunStory, RunStoryChild } from '@/lib/types/engine';

export type { ReadDocument };

/** The email the run began with: who sent it, when, its text and its attachments. */
export function RunEmailSection({ email }: { email: RunEmail }) {
  return (
    <Section title="Email" description={email.receivedAt ? `Received ${relativeTime(email.receivedAt)}` : 'The email this run started from'}>
      <div className="flex flex-col gap-3" data-testid="run-email">
        <div>
          <FieldRow label="From" value={email.from} wrap testId="run-email-from" />
          <FieldRow label="Subject" value={email.subject || 'No subject'} wrap testId="run-email-subject" />
          {email.receivedAt && <FieldRow label="Received" value={dateTime(email.receivedAt)} wrap />}
          {email.mailbox && <FieldRow label="Mailbox" value={email.mailbox} wrap />}
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Text</span>
          <p className="max-h-64 overflow-y-auto rounded-md border bg-muted/30 p-3 text-sm break-words whitespace-pre-wrap" data-testid="run-email-body">
            {email.body.trim() || <span className="text-muted-foreground">The email had no text.</span>}
          </p>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">{email.attachments.length ? plural(email.attachments.length, 'attachment') : 'No attachments'}</span>
          {!!email.attachments.length && (
            <Rows className="rounded-md border" testId="run-email-attachments">
              {email.attachments.map((a) => (
                <Row
                  key={a.fileId}
                  href={`/files/${encodeURIComponent(a.fileId)}`}
                  leading={<FileText className="size-4 text-muted-foreground" />}
                  title={a.name}
                  description={[a.type ? mimeLabel(a.type) : null, a.size != null ? bytes(a.size) : null].filter(Boolean).join(' · ') || undefined}
                />
              ))}
            </Rows>
          )}
          {!!email.skipped.length && (
            <div className="flex flex-col gap-1 text-xs text-muted-foreground" data-testid="run-email-skipped">
              {email.skipped.map((s) => (
                <p key={s.name} className="break-words">
                  Not stored: {s.name}. {s.message}
                </p>
              ))}
            </div>
          )}
        </div>
      </div>
    </Section>
  );
}

/** What a document-read step read: the document with each field's place highlighted, and the fields with their confidence. */
export function RunReadSection({ item, document, title }: { item: RunRead; document?: ReadDocument; title?: string }) {
  const records = item.read.records.length;
  return (
    <Section title={title ?? item.name} description={`${plural(records, 'record')} read from ${item.read.fileName ?? 'the document'}. Choose a field's source to see where it was read.`}>
      <div data-testid={`run-read-${item.nodeId}`}>
        {records ? <DocumentReadView read={item.read} document={document} /> : <p className="text-sm text-muted-foreground">Nothing was read from this document.</p>}
      </div>
    </Section>
  );
}

/** One run it started: what it was about, where it is now, and the case and Human Task it opened. */
/** One run it started: what it was about, where it is now, its case's customer and facts, its Human Task, and links. */
function ChildRow({ child, testId }: { child: RunStoryChild; testId: string }) {
  const task = child.tasks.find((t) => t.open) ?? child.tasks[child.tasks.length - 1];
  const kase = child.cases[0];
  const facts = kase ? [...(kase.customer ? [{ label: 'Customer', value: kase.customer }] : []), ...kase.facts] : [];
  return (
    <Row wrap title={child.label} description={`${child.state} · ${child.workflowName}`} trailing={<RunStatus status={child.status} testId={`run-child-${child.index}`} />}>
      <div className="mt-1 flex flex-col gap-1 text-xs" data-testid={testId} data-state={child.state}>
        {facts.length > 0 && (
          <p className="break-words text-muted-foreground" data-testid={`${testId}-facts`}>
            {facts.map((f) => `${f.label}: ${f.value}`).join(' · ')}
          </p>
        )}
        {task && (
          <p className="break-words" data-testid={`${testId}-task-state`}>
            {task.state}
          </p>
        )}
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          <Link href={`/workflows/runs/${encodeURIComponent(child.runId)}`} className="font-medium underline underline-offset-2" data-testid={`${testId}-run`}>
            Open run
          </Link>
          {kase && (
            <Link href={`/cases/${encodeURIComponent(kase.caseId)}`} className="font-medium break-words underline underline-offset-2" data-testid={`${testId}-case`}>
              Case: {kase.subject}
            </Link>
          )}
          {task && (
            <Link href={`/reviews/${encodeURIComponent(task.reviewId)}`} className="font-medium underline underline-offset-2" data-testid={`${testId}-task`}>
              {task.open ? 'Open Human Task' : 'View Human Task'}
            </Link>
          )}
        </div>
      </div>
    </Row>
  );
}

/**
 * A run told from its steps' output shapes, as the API returns it: the email it began with, each document it read
 * beside the document, and one row per run it started. What a started run read or started in turn is on its own page,
 * as n8n, Camunda Operate and Power Automate show sub-runs.
 */
export function RunStoryView({ story, document }: { story: RunStory; document?: ReadDocument }) {
  return (
    <>
      {story.email && <RunEmailSection email={story.email} />}
      {story.reads.map((r) => (
        <RunReadSection key={r.nodeId} item={r} document={document} />
      ))}
      {story.children.length > 0 && (
        <Section
          title={`Runs it started · ${story.children.length + story.childrenMore}`}
          description={story.childrenMore ? `The first ${story.children.length} are listed; the runs list has the other ${story.childrenMore}.` : 'What each was about, where it is now, and the case and Human Task it opened.'}
          actions={
            story.childrenMore ? (
              <Button asChild variant="outline" size="sm">
                <Link href="/workflows/runs">All runs</Link>
              </Button>
            ) : undefined
          }
          flush
        >
          <Rows testId="run-children">
            {story.children.map((c) => (
              <ChildRow key={c.runId} child={c} testId={`run-children-${c.index}`} />
            ))}
          </Rows>
        </Section>
      )}
    </>
  );
}
