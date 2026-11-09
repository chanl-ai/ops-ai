'use client';

import * as React from 'react';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { KnowledgeChange } from '@/lib/types/knowledge-changes';

import { FaqCheck } from './change-chips';
import { decidable } from './change-columns';

type Act = 'save' | 'approve' | 'reject';

/**
 * An FAQ draft opened for review: its question and answer editable, the passage it quotes read only. Approve saves an
 * edit first, so what is approved is what was read here. A draft already decided shows read only.
 */
export function FaqDraftEditor({ change: c, busy, onAct }: { change: KnowledgeChange; busy: Act | null; onAct: (act: Act, pair: { question: string; answer: string }) => void }) {
  const [question, setQuestion] = React.useState(c.faq?.question ?? '');
  const [answer, setAnswer] = React.useState(c.faq?.answer ?? '');
  React.useEffect(() => {
    setQuestion(c.faq?.question ?? '');
    setAnswer(c.faq?.answer ?? '');
  }, [c.id, c.faq?.question, c.faq?.answer]);
  const editable = decidable(c);
  const edited = question.trim() !== (c.faq?.question ?? '') || answer.trim() !== (c.faq?.answer ?? '');
  const missing = !question.trim() ? 'Write the question.' : !answer.trim() ? 'Write the answer.' : undefined;
  const pair = { question: question.trim(), answer: answer.trim() };

  return (
    <div className="flex flex-col gap-5" data-testid="faq-draft-editor">
      <FormField id="faq-question" label="Question" error={!question.trim() ? missing : undefined}>
        <Input id="faq-question" value={question} onChange={(e) => setQuestion(e.target.value)} disabled={!editable} maxLength={300} />
      </FormField>
      <FormField id="faq-answer" label="Answer" hint="Only what the passage says. The citation points at the passage." error={question.trim() && !answer.trim() ? missing : undefined}>
        <Textarea id="faq-answer" value={answer} onChange={(e) => setAnswer(e.target.value)} disabled={!editable} rows={4} />
      </FormField>
      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium">Source passage</p>
        <blockquote className="rounded-md border bg-muted/30 p-3 text-sm">“{c.before}”</blockquote>
        <p className="text-xs text-muted-foreground">
          {c.faq?.sectionPath.length ? c.faq.sectionPath.join(' › ') : `${c.documentTitle} › ${c.section}`} · {c.sourceName} · {c.toVersion}
        </p>
      </div>
      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium">Check</p>
        <FaqCheck change={c} />
      </div>
      {editable ? (
        <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
          <LoadingButton variant="outline" className="text-destructive-text" isLoading={busy === 'reject'} disabled={!!busy} onClick={() => onAct('reject', pair)} data-testid="faq-reject">
            Reject
          </LoadingButton>
          <LoadingButton variant="outline" isLoading={busy === 'save'} disabled={!!busy || !edited || !!missing} onClick={() => onAct('save', pair)} data-testid="faq-save">
            Save edit
          </LoadingButton>
          <LoadingButton isLoading={busy === 'approve'} disabled={!!busy || !!missing} onClick={() => onAct('approve', pair)} data-testid="faq-approve">
            {edited ? 'Save and approve' : 'Approve'}
          </LoadingButton>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{c.canDecide ? 'This draft is decided.' : `Only the knowledge owner of ${c.sourceName} decides this draft.`}</p>
      )}
    </div>
  );
}

/** Whether approving `pair` must save it first: the person changed the question or the answer. */
export const needsSave = (c: KnowledgeChange, pair: { question: string; answer: string }) => pair.question !== (c.faq?.question ?? '') || pair.answer !== (c.faq?.answer ?? '');
