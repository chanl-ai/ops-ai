'use client';

import * as React from 'react';
import { AlertTriangle, BookOpenCheck, Brain, Copy, ListTree, Paperclip, Pencil, RefreshCw, SearchX, ShieldAlert, Square, ThumbsDown, ThumbsUp } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { ChatAction, ChatBubble, ChatResponse, ChatThinking } from '@/components/shared/chat-blocks';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Textarea } from '@/components/ui/textarea';
import { bytes } from '@/lib/format';
import type { ChatMessage, MessageFeedback, WidgetAction } from '@/lib/types/chat';
import { isLayoutPart } from '@/lib/types/widgets';

import { CitationPopover, SourcesList } from './citation-popover';
import { ToolCallCard } from './tool-call-card';
import { LayoutWidget } from './widget-layout';
import { WidgetView } from './widget-view';
import { ChatWidgetView } from './widgets';

const FEEDBACK_REASONS = ['Wrong answer', 'Missing from the knowledge base', 'Cited the wrong document', 'Tool returned the wrong data', 'Not what I asked'];

export function UserMessage({ message, onEdit, disabled }: { message: ChatMessage; onEdit?: (text: string) => void; disabled?: boolean }) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(message.content);
  if (editing)
    return (
      <div className="ml-auto w-full max-w-[85%] space-y-2">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
          autoFocus
          aria-label="Edit message"
          onKeyDown={(e) => {
            if (e.key === 'Escape') setEditing(false);
          }}
        />
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={() => setEditing(false)}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!draft.trim() || draft.trim() === message.content}
            onClick={() => {
              onEdit?.(draft.trim());
              setEditing(false);
            }}
          >
            Save and resend
          </Button>
        </div>
        <p className="text-right text-xs text-muted-foreground">Everything after this message is replaced by the new answer.</p>
      </div>
    );
  return (
    <div className="flex flex-col items-end gap-1">
      {message.attachments?.map((a) => (
        <span key={a.name} className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-muted-foreground">
          <Paperclip className="size-3" /> {a.name} · {bytes(a.size)}
        </span>
      ))}
      <ChatBubble
        from="user"
        className="max-w-[85%]"
        actions={
          onEdit &&
          !disabled && (
            <ChatAction
              label="Edit and resend"
              onClick={() => {
                setDraft(message.content);
                setEditing(true);
              }}
            >
              <Pencil className="size-3.5" />
            </ChatAction>
          )
        }
      >
        {message.content}
      </ChatBubble>
    </div>
  );
}

export function AssistantMessage({
  message,
  phaseLabel,
  streaming,
  readOnly,
  noAnswerHint,
  onOpenDocument,
  onCopy,
  onRegenerate,
  onFeedback,
  onWidgetAction,
  onReply,
  onOpenTrace,
  budgetCard,
  byline,
  onOpenMemory,
}: {
  message: ChatMessage;
  /** Set while the reply is in flight and nothing has been written yet. */
  phaseLabel?: string;
  streaming?: boolean;
  readOnly?: boolean;
  noAnswerHint?: React.ReactNode;
  onOpenDocument: (documentId: string, page?: number) => void;
  onCopy: (text: string) => void;
  onRegenerate?: () => void;
  onFeedback?: (feedback: MessageFeedback | null) => void;
  onWidgetAction?: (widgetId: string, action: WidgetAction) => Promise<unknown>;
  /** Sends a widget button's reply as the person's next message (c-082); undefined in a read-only conversation. */
  onReply?: (text: string) => void;
  /** Opens how the cited passages were found: queries, filters, scores and precedence. */
  onOpenTrace?: (trace: NonNullable<ChatMessage['trace']>) => void;
  /** The conversation's budget card when this turn paused on it (c-103); the page decides who may answer. */
  budgetCard?: React.ReactNode;
  /** Names the agent that wrote this reply, shown once a conversation has had more than one agent (c-174). */
  byline?: string;
  /** Opens What I remember from the line saying what this reply saved (c-206); absent in someone else's chat. */
  onOpenMemory?: () => void;
}) {
  const [feedbackOpen, setFeedbackOpen] = React.useState(false);
  const [reason, setReason] = React.useState(FEEDBACK_REASONS[0]);
  const [comment, setComment] = React.useState('');
  const cites = message.citations ?? [];
  const renderCitation = (n: number) => {
    const c = cites.find((x) => x.n === n);
    return c ? <CitationPopover citation={c} onOpenDocument={onOpenDocument} onOpenTrace={message.trace && onOpenTrace ? () => onOpenTrace(message.trace!) : undefined} /> : null;
  };
  const settled = !streaming && !phaseLabel;

  return (
    <div className="group flex flex-col gap-2">
      {byline && (
        <span className="text-xs font-medium text-muted-foreground" data-testid="reply-agent">
          {byline}
        </span>
      )}
      {message.toolCalls?.map((c) => <ToolCallCard key={c.id} call={c} />)}
      {message.widgets?.map((w) => (
        <ChatWidgetView key={w.id} widget={w} onAction={readOnly || !onWidgetAction ? undefined : (a) => onWidgetAction(w.id, a)} />
      ))}
      {message.parts?.map((p) => (isLayoutPart(p) ? <LayoutWidget key={p.id} part={p} onReply={readOnly ? undefined : onReply} /> : <WidgetView key={p.id} part={p} />))}

      {phaseLabel && !message.content ? (
        <ChatThinking label={phaseLabel} />
      ) : message.noAnswer && settled ? (
        <div className="flex items-start gap-2 rounded-md border border-dashed px-3 py-2 text-sm">
          <SearchX className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="space-y-1">
            <p>{message.content}</p>
            {noAnswerHint}
          </div>
        </div>
      ) : message.content ? (
        <ChatResponse text={message.content} renderCitation={renderCitation} streaming={streaming} citations={cites.length} />
      ) : null}

      {settled && cites.length > 0 && <SourcesList citations={cites} onOpenDocument={onOpenDocument} />}
      {settled && message.trace && onOpenTrace && (
        <button type="button" onClick={() => onOpenTrace(message.trace!)} className="flex w-fit items-center gap-1 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
          <ListTree className="size-3" /> How this was found · {message.trace.candidates.filter((c) => c.outcome === 'returned').length} of {message.trace.searched} passages
          {message.trace.precedence.length ? ` · ${message.trace.precedence.length} precedence ${message.trace.precedence.length === 1 ? 'decision' : 'decisions'}` : ''}
        </button>
      )}

      {message.skills?.length && settled ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="loaded-skills">
          <BookOpenCheck className="size-3" />
          {message.skills.map((s) => `Loaded skill ${s.name} v${s.version}`).join(' · ')}
        </p>
      ) : null}

      {message.remembered?.length && settled ? (
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground" data-testid="saved-to-memory">
          <Brain className="size-3" />
          Saved to memory: {message.remembered.map((r) => (r.key ? `${r.key}: ${r.value}` : r.value)).join(' · ')}
          {onOpenMemory && (
            <button type="button" onClick={onOpenMemory} className="underline-offset-4 hover:text-foreground hover:underline" data-testid="open-memory">
              What I remember
            </button>
          )}
        </p>
      ) : null}

      {message.guardrail && settled && (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="guardrail-refusal">
          <ShieldAlert className="size-3" />
          {{ before: 'Not answered', after: 'Answer withdrawn', corrected: 'Answer rewritten' }[message.guardrail.when]}: {message.guardrail.name} v{message.guardrail.version} blocks “{message.guardrail.topic}”.
        </p>
      )}

      {message.guardrailAudit?.length && settled ? (
        // Present only for a reader the roles grid lets view the audit: what the guardrail kept or took back.
        <Collapsible data-testid="guardrail-audit">
          <CollapsibleTrigger asChild>
            <Button variant="link" size="sm" className="h-auto px-0 text-xs text-muted-foreground">
              <ShieldAlert className="size-3" /> Audit: what the guardrail {message.guardrailAudit.some((a) => a.kind === 'retracted') ? 'took back' : 'kept back'}
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="space-y-2 pt-1">
            {message.guardrailAudit.map((a, i) => (
              <div key={i} className="rounded-md border bg-muted/40 p-2 text-xs">
                <p className="text-muted-foreground">
                  {a.kind === 'retracted' ? 'Shown, then withdrawn' : 'Never shown'}
                  {a.guardrail ? ` · ${a.guardrail.name} v${a.guardrail.version} · “${a.guardrail.topic}”` : ''}
                  {a.at ? ` · ${new Date(a.at).toLocaleString()}` : ''}
                </p>
                <p className="mt-1 whitespace-pre-wrap break-words">{a.text}</p>
              </div>
            ))}
          </CollapsibleContent>
        </Collapsible>
      ) : null}

      {budgetCard}

      {message.stopped && settled && (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Square className="size-3" /> Stopped. The answer above is what arrived before you stopped it.
        </p>
      )}

      {message.error && settled && (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>The answer stopped part-way</AlertTitle>
          <AlertDescription className="space-y-2">
            <p>{message.error}</p>
            {onRegenerate && !readOnly && (
              <Button size="sm" variant="outline" className="border-destructive/40 text-foreground" onClick={onRegenerate}>
                <RefreshCw className="size-3.5" /> Retry
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      {settled && !message.error && message.content && (
        <div className="flex flex-wrap items-center gap-0.5 opacity-100 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:focus-within:opacity-100">
          <ChatAction label="Copy" onClick={() => onCopy(message.content.replace(/\s?\[\^?\d+\]/g, ''))}>
            <Copy className="size-3.5" />
          </ChatAction>
          {!readOnly && onRegenerate && (
            <ChatAction label="Regenerate" onClick={onRegenerate}>
              <RefreshCw className="size-3.5" />
            </ChatAction>
          )}
          {!readOnly && onFeedback && (
            <>
              <ChatAction label="Good answer" active={message.feedback?.rating === 'up'} onClick={() => onFeedback(message.feedback?.rating === 'up' ? null : { rating: 'up' })}>
                <ThumbsUp className="size-3.5" />
              </ChatAction>
              <ChatAction
                label={message.feedback?.rating === 'down' ? `Bad answer: ${message.feedback.reason ?? 'no reason'}` : 'Bad answer'}
                active={message.feedback?.rating === 'down'}
                onClick={() => (message.feedback?.rating === 'down' ? onFeedback(null) : setFeedbackOpen(true))}
              >
                <ThumbsDown className="size-3.5" />
              </ChatAction>
            </>
          )}
        </div>
      )}
      {readOnly && message.feedback && (
        <p className="flex items-center gap-1 text-xs text-muted-foreground">
          {message.feedback.rating === 'up' ? <ThumbsUp className="size-3" /> : <ThumbsDown className="size-3" />} Rated {message.feedback.rating === 'up' ? 'helpful' : `not helpful${message.feedback.reason ? `: ${message.feedback.reason}` : ''}`}
        </p>
      )}

      <DialogShell
        open={feedbackOpen}
        onOpenChange={setFeedbackOpen}
        size="sm"
        title="What was wrong with this answer?"
        description="Feedback goes to the agent’s owner and shows in its test suite as a candidate case."
        footer={
          <>
            <Button variant="outline" onClick={() => setFeedbackOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                onFeedback?.({ rating: 'down', reason: comment.trim() ? `${reason}: ${comment.trim()}` : reason });
                setFeedbackOpen(false);
                setComment('');
              }}
            >
              Send feedback
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <RadioGroup value={reason} onValueChange={setReason} className="gap-2">
            {FEEDBACK_REASONS.map((r) => (
              <div key={r} className="flex items-center gap-2">
                <RadioGroupItem value={r} id={`fb-${r}`} />
                <Label htmlFor={`fb-${r}`} className="font-normal">
                  {r}
                </Label>
              </div>
            ))}
          </RadioGroup>
          <FormField id="fb-comment" label="Details" optional>
            <Textarea id="fb-comment" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="The playbook was updated to v5.1 last week" />
          </FormField>
        </div>
      </DialogShell>
    </div>
  );
}
