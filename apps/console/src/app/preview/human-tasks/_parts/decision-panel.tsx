'use client';

import * as React from 'react';
import { Check, LockKeyhole, MessageSquareMore, UserRoundPlus } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FieldRow, FieldSectionLabel } from '@/components/shared/field-row';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Note } from '@/components/shared/setting/note';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

import { dueText, isSoon, KIND_LABEL, ME, PEOPLE, type QueueItem, type Task } from '../_sample/data';
import type { ReviewQueue } from './use-review-queue';

/**
 * The decision, top to bottom: what is asked, the facts that decide it, each option with what it does, a reason, and
 * Decide. The header and the Decide row never scroll; only the middle does, and only when the window is too short for
 * it. A notice naming several people is one item with a tab per person, each decided on its own.
 */
export function DecisionPanel({ item, task, queue, className }: { item: QueueItem; task: Task; queue: ReviewQueue; className?: string }) {
  const decided = queue.decisions[task.id];
  const [option, setOption] = React.useState(task.suggested ?? task.options[0].id);
  const [reason, setReason] = React.useState('');
  const [confirming, setConfirming] = React.useState(false);
  const [asking, setAsking] = React.useState(false);
  React.useEffect(() => {
    setOption(task.suggested ?? task.options[0].id);
    setReason('');
  }, [task.id, task.suggested, task.options]);
  const chosen = task.options.find((o) => o.id === option) ?? task.options[0];

  const record = () => queue.decide(item, task, chosen.id, reason.trim());
  const submit = () => (chosen.stepUp ? setConfirming(true) : record());

  return (
    <aside className={cn('flex min-h-0 min-w-0 flex-col rounded-lg border bg-card', className)} aria-label="Decision" data-testid="decision-panel">
      <header className="flex flex-col gap-3 border-b p-4">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span>{KIND_LABEL[item.kind]}</span>
          <span aria-hidden>·</span>
          <span>Case {item.caseRef}</span>
          <span aria-hidden>·</span>
          <span className={cn('tabular-nums', isSoon(item.due) && 'font-medium text-warning-text')}>{dueText(item.due)}</span>
          <span aria-hidden>·</span>
          <span>{item.assignee === ME ? 'Assigned to you' : `Assigned to ${item.assignee}`}</span>
        </div>
        {item.tasks.length > 1 && (
          <Tabs value={task.id} onValueChange={queue.open}>
            <TabsList className="h-auto w-full flex-wrap justify-start" aria-label="People on this notice">
              {item.tasks.map((t) => (
                <TabsTrigger key={t.id} value={t.id} className="h-8 min-w-0 flex-none" data-testid={`subject-tab-${t.id}`}>
                  {queue.decisions[t.id] && <Check className="size-3.5 text-success-text" aria-label="Decided" />}
                  <span className="truncate">{t.subject}</span>
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        )}
        <h2 className="text-base font-semibold leading-snug" data-testid="decision-question">
          {task.question}
        </h2>
      </header>

      <form
        id={`decide-${task.id}`}
        className="flex min-h-0 flex-1 flex-col"
        onSubmit={(e) => {
          e.preventDefault();
          if (!decided) submit();
        }}
      >
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4" data-testid="decision-body">
          <div data-testid="decision-facts">
            <FieldSectionLabel>What decides it</FieldSectionLabel>
            {task.facts.map((f) => (
              <FieldRow key={f.label} label={f.label} wrap value={<span className={cn('tabular-nums', f.warn && 'font-medium text-warning-text')}>{f.value}</span>} />
            ))}
          </div>

          {task.warning && (
            <div data-testid="over-balance">
              <Note tone="warning" title={task.warning.title}>
                {task.warning.body}
              </Note>
            </div>
          )}

          {decided ? (
            <Note tone="info" title={`Decided by ${decided.by}`}>
              {task.options.find((o) => o.id === decided.option)?.label}
              {decided.reason ? `: ${decided.reason}` : ''}
            </Note>
          ) : (
            <>
              <fieldset className="flex flex-col gap-2">
                <legend className="mb-2 text-sm font-medium">Your decision</legend>
                <RadioGroup value={option} onValueChange={setOption} className="gap-2">
                  {task.options.map((o) => (
                    <Label
                      key={o.id}
                      htmlFor={`opt-${task.id}-${o.id}`}
                      className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3 font-normal transition-colors hover:bg-accent/50', option === o.id && 'border-primary bg-accent/40')}
                      data-testid={`option-${o.id}`}
                    >
                      <RadioGroupItem id={`opt-${task.id}-${o.id}`} value={o.id} className="mt-0.5" />
                      <span className="flex min-w-0 flex-col gap-1">
                        <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                          {o.label}
                          {o.id === task.suggested && <Badge variant="secondary">Suggested</Badge>}
                          {o.stepUp && (
                            <span className="inline-flex items-center gap-1 text-xs font-normal text-muted-foreground">
                              <LockKeyhole className="size-3" aria-hidden /> Needs a fresh sign-in
                            </span>
                          )}
                        </span>
                        <span className="text-xs leading-relaxed text-muted-foreground">{o.consequence}</span>
                      </span>
                    </Label>
                  ))}
                </RadioGroup>
              </fieldset>
              <FormField id={`reason-${task.id}`} label="Reason" optional hint="Kept on the case with your name and the time.">
                <Textarea id={`reason-${task.id}`} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Balance confirmed with the branch" />
              </FormField>
            </>
          )}
        </div>

        {/* Sticky for the one-pane phone view, where the page scrolls; beside the evidence the panel is bounded and it never moves. */}
        <footer className="sticky bottom-0 flex flex-col gap-2 rounded-b-lg border-t bg-card p-4" data-testid="decision-footer">
          <Button type="submit" className="w-full" disabled={!!decided} data-testid="decide">
            {decided ? 'Decided' : chosen.label}
          </Button>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" className="flex-1" onClick={() => setAsking(true)} data-testid="ask-info">
              <MessageSquareMore /> Ask for more info
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button type="button" variant="outline" size="sm" className="flex-1" data-testid="reassign">
                  <UserRoundPlus /> Reassign
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>Reassign this {item.kind === 'court_order' ? 'notice' : 'dispute'} to</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {PEOPLE.map((p) => (
                  <DropdownMenuItem key={p} onSelect={() => queue.reassign(item, p)}>
                    {p}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </footer>
      </form>

      <ConfirmItsYou
        open={confirming}
        noun={chosen.stepUp ?? 'decision'}
        onOpenChange={setConfirming}
        onConfirmed={() => {
          setConfirming(false);
          record();
        }}
      />
      <AskForInfo open={asking} item={item} onOpenChange={setAsking} onSend={(note) => queue.askForInfo(item, note)} />
    </aside>
  );
}

/** The step-up before money moves. It says what it is for in one line, asks for this person's password, and nothing else. */
function ConfirmItsYou({ open, noun, onOpenChange, onConfirmed }: { open: boolean; noun: string; onOpenChange: (o: boolean) => void; onConfirmed: () => void }) {
  const [password, setPassword] = React.useState('');
  const [error, setError] = React.useState<string>();
  const [pending, setPending] = React.useState(false);
  React.useEffect(() => {
    // The typed password leaves the DOM whenever the dialog closes.
    if (!open) {
      setPassword('');
      setError(undefined);
      setPending(false);
    }
  }, [open]);
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title="Confirm it's you"
      description={`This ${noun} needs a fresh sign-in.`}
      onSubmit={() => {
        if (!password) return setError('Enter your password.');
        setPending(true);
        window.setTimeout(onConfirmed, 400);
      }}
      footer={
        <div className="flex w-full flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={pending} loadingText="Signing in…" data-testid="confirm-submit">
            <LockKeyhole className="size-4" /> Sign in and {noun === 'hold' ? 'place the hold' : 'give the credit'}
          </LoadingButton>
        </div>
      }
    >
      <div data-testid="confirm-its-you">
        <FormField id="step-up-password" label="Your password" error={error} hint="You won't be asked again for 5 minutes.">
          <Input id="step-up-password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} aria-invalid={!!error} autoFocus />
        </FormField>
      </div>
    </DialogShell>
  );
}

/** Ask the case owner a question; the item leaves the queue until the answer comes back to this person. */
function AskForInfo({ open, item, onOpenChange, onSend }: { open: boolean; item: QueueItem; onOpenChange: (o: boolean) => void; onSend: (note: string) => void }) {
  const [note, setNote] = React.useState('');
  const [error, setError] = React.useState<string>();
  React.useEffect(() => {
    if (open) {
      setNote('');
      setError(undefined);
    }
  }, [open]);
  const who = item.kind === 'court_order' ? 'the Legal Process Unit' : 'the branch that took the dispute';
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Ask for more information"
      description={`Your question goes to ${who}. ${item.title} leaves your queue and comes back with the answer.`}
      onSubmit={() => {
        if (!note.trim()) return setError('Say what you need to decide.');
        onOpenChange(false);
        onSend(note.trim());
      }}
      footer={
        <div className="flex w-full flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit">Send question</Button>
        </div>
      }
    >
      <FormField id="ask-note" label="What do you need?" error={error}>
        <Textarea id="ask-note" rows={4} value={note} onChange={(e) => setNote(e.target.value)} aria-invalid={!!error} placeholder="e.g. Is there a second account for this person?" autoFocus />
      </FormField>
    </DialogShell>
  );
}
