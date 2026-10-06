'use client';

import * as React from 'react';
import { AlertTriangle, Copy, ListTree, Paperclip, Pencil, RefreshCw, SearchX, Square, ThumbsDown, ThumbsUp } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Textarea } from '@/components/ui/textarea';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { bytes } from '@/lib/format';
import type { ChatMessage, MessageFeedback, WidgetAction } from '@/lib/types/chat';
import { cn } from '@/lib/utils';

import { CitationPopover, SourcesList } from './citation-popover';
import { RichText } from './rich-text';
import { ToolCallCard } from './tool-call-card';
import { WidgetView } from './widgets';

const FEEDBACK_REASONS = ['Wrong answer', 'Missing from the knowledge base', 'Cited the wrong document', 'Tool returned the wrong data', 'Not what I asked'];

function IconAction({ label, onClick, active, children }: { label: string; onClick: () => void; active?: boolean; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon" className={cn('size-7', active && 'bg-accent text-foreground')} onClick={onClick} aria-label={label} aria-pressed={active}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

export function ThinkingLine({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 py-1 text-xs text-muted-foreground" role="status">
      <span className="flex gap-1">
        {[0, 150, 300].map((d) => (
          <span key={d} className="size-1.5 animate-pulse rounded-full bg-muted-foreground" style={{ animationDelay: `${d}ms` }} />
        ))}
      </span>
      {label}
    </div>
  );
}

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
    <div className="group flex flex-col items-end gap-1">
      {message.attachments?.map((a) => (
        <span key={a.name} className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-muted-foreground">
          <Paperclip className="size-3" /> {a.name} · {bytes(a.size)}
        </span>
      ))}
      <div className="max-w-[85%] rounded-lg bg-muted px-3 py-2 text-sm whitespace-pre-wrap">{message.content}</div>
      {onEdit && !disabled && (
        <div className="opacity-100 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:focus-within:opacity-100">
          <IconAction
            label="Edit and resend"
            onClick={() => {
              setDraft(message.content);
              setEditing(true);
            }}
          >
            <Pencil className="size-3.5" />
          </IconAction>
        </div>
      )}
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
  onOpenTrace,
}: {
  message: ChatMessage;
  /** Set while the reply is in flight and nothing has been written yet. */
  phaseLabel?: string;
  streaming?: boolean;
  readOnly?: boolean;
  noAnswerHint?: React.ReactNode;
  onOpenDocument: (documentId: string) => void;
  onCopy: (text: string) => void;
  onRegenerate?: () => void;
  onFeedback?: (feedback: MessageFeedback | null) => void;
  onWidgetAction?: (widgetId: string, action: WidgetAction) => Promise<unknown>;
  /** Opens how the cited passages were found: queries, filters, scores and precedence. */
  onOpenTrace?: (trace: NonNullable<ChatMessage['trace']>) => void;
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
      {message.toolCalls?.map((c) => <ToolCallCard key={c.id} call={c} />)}
      {message.widgets?.map((w) => (
        <WidgetView key={w.id} widget={w} onAction={readOnly || !onWidgetAction ? undefined : (a) => onWidgetAction(w.id, a)} />
      ))}

      {phaseLabel && !message.content ? (
        <ThinkingLine label={phaseLabel} />
      ) : message.noAnswer && settled ? (
        <div className="flex items-start gap-2 rounded-md border border-dashed px-3 py-2 text-sm">
          <SearchX className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="space-y-1">
            <p>{message.content}</p>
            {noAnswerHint}
          </div>
        </div>
      ) : message.content ? (
        <div>
          <RichText text={message.content} renderCitation={renderCitation} streaming={streaming} />
          {streaming && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-foreground/60 align-middle" />}
        </div>
      ) : null}

      {settled && cites.length > 0 && <SourcesList citations={cites} onOpenDocument={onOpenDocument} />}
      {settled && message.trace && onOpenTrace && (
        <button type="button" onClick={() => onOpenTrace(message.trace!)} className="flex w-fit items-center gap-1 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
          <ListTree className="size-3" /> How this was found · {message.trace.candidates.filter((c) => c.outcome === 'returned').length} of {message.trace.searched} passages
          {message.trace.precedence.length ? ` · ${message.trace.precedence.length} precedence ${message.trace.precedence.length === 1 ? 'decision' : 'decisions'}` : ''}
        </button>
      )}

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
          <IconAction label="Copy" onClick={() => onCopy(message.content.replace(/\s?\[\^?\d+\]/g, ''))}>
            <Copy className="size-3.5" />
          </IconAction>
          {!readOnly && onRegenerate && (
            <IconAction label="Regenerate" onClick={onRegenerate}>
              <RefreshCw className="size-3.5" />
            </IconAction>
          )}
          {!readOnly && onFeedback && (
            <>
              <IconAction label="Good answer" active={message.feedback?.rating === 'up'} onClick={() => onFeedback(message.feedback?.rating === 'up' ? null : { rating: 'up' })}>
                <ThumbsUp className="size-3.5" />
              </IconAction>
              <IconAction
                label={message.feedback?.rating === 'down' ? `Bad answer: ${message.feedback.reason ?? 'no reason'}` : 'Bad answer'}
                active={message.feedback?.rating === 'down'}
                onClick={() => (message.feedback?.rating === 'down' ? onFeedback(null) : setFeedbackOpen(true))}
              >
                <ThumbsDown className="size-3.5" />
              </IconAction>
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
