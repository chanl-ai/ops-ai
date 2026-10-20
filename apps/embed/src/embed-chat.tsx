'use client';

import * as React from 'react';
import { AlertTriangle, Bot, LogIn, MoreHorizontal, RotateCcw, X } from 'lucide-react';

import { BudgetCard } from '@/components/chat/budget-card';
import { Composer } from '@/components/chat/composer';
import { SendFailedAlert } from '@/components/chat/send-failed';
import { AssistantMessage, UserMessage } from '@/components/chat/message-view';
import { ChatConversation } from '@/components/shared/chat-blocks';
import { EmptyState } from '@/components/shared/empty-state';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { type LiveTurn, useAnswerBudget, useChatThread, useCreateThread, useLiveTurn, useSendMessage } from '@/hooks/chat-queries';
import type { ChatMessage, ChatThread } from '@/lib/types/chat';

/** Thread history with the in-flight turn spliced in, as the console chat shows it. */
function visible(thread: ChatThread | undefined, live: LiveTurn | undefined): ChatMessage[] {
  const base = thread?.messages ?? [];
  if (!live) return base;
  const kept = base.filter((m) => m.id !== live.userMessage?.id && m.id !== live.assistant.id);
  return [...kept, ...(live.userMessage ? [live.userMessage] : []), ...(live.failed ? [] : [live.assistant])];
}

export interface EmbedChatProps {
  agentName: string;
  suggestions: string[];
  /** Who the session names; null when the page has no session (signed out). */
  person: { name: string } | null;
  /** The session ended and the page had no fresh one, or the service refused it. */
  error?: 'session_expired' | 'unavailable';
  /** Whether the host page registered a login the Sign in button can run. */
  canSignIn: boolean;
  /** The conversation this tab had open, if any; the page keeps it per tab. */
  threadId?: string;
  onThread: (id: string | undefined) => void;
  onSignIn: () => void;
  onClose: () => void;
  onMessage: (role: 'user' | 'assistant') => void;
}

/**
 * The embedded chat (c-158): header, messages, starter questions, composer and footer, drawn from the console's own chat
 * components, so citations, answer widgets, tool cards, the approval card and the budget card are the console's. The
 * thread is created on the first message, never on open. Widgets take no actions here: a widget session approves for
 * no team, so an approval is decided in Human Tasks and the conversation carries on here, and form submit is not built.
 */
export function EmbedChat({ agentName, suggestions, person, error, canSignIn, threadId, onThread, onSignIn, onClose, onMessage }: EmbedChatProps) {
  const thread = useChatThread(threadId);
  const live = useLiveTurn(threadId);
  const chat = useSendMessage();
  const create = useCreateThread();
  const budget = useAnswerBudget();
  const streaming = !!live?.streaming;
  const messages = visible(thread.data, live);
  const wasStreaming = React.useRef(false);

  // The page hears that a reply arrived (for an unread badge), never what it says.
  React.useEffect(() => {
    if (wasStreaming.current && !streaming) onMessage('assistant');
    wasStreaming.current = streaming;
  }, [streaming, onMessage]);

  // A send the service refuses (an origin it does not allow, an expired key) keeps its text and says why; it never
  // leaves the box without a reply or a reason.
  const [notSent, setNotSent] = React.useState<{ text: string; message: string } | null>(null);
  const send = async (text: string) => {
    setNotSent(null);
    onMessage('user');
    try {
      if (threadId) return await chat.send(threadId, { content: text });
      const t = await create.mutateAsync({ agentId: '', kbIds: [] });
      onThread(t.id);
      await chat.send(t.id, { content: text });
    } catch (e) {
      setNotSent({ text, message: e instanceof Error && e.message ? e.message : 'The assistant could not take your message.' });
    }
  };
  const failed = notSent ?? (live?.failed ? { text: live.failed.input.content, message: live.failed.message } : null);

  const body = !person ? (
    <div className="flex flex-1 items-center justify-center p-4">
      <EmptyState
        icon={LogIn}
        title="Sign in to use the assistant"
        description={canSignIn ? `${agentName} needs to know who you are.` : 'Sign in to the intranet, then open the chat again.'}
        action={canSignIn ? { label: 'Sign in', onClick: onSignIn } : undefined}
        testId="embed-signed-out"
      />
    </div>
  ) : error ? (
    <div className="flex-1 p-4" data-testid="embed-error">
      <Alert variant="destructive">
        <AlertTriangle className="size-4" />
        <AlertTitle>{error === 'session_expired' ? 'Your session ended' : 'The assistant is unavailable'}</AlertTitle>
        <AlertDescription className="space-y-2">
          <p>{error === 'session_expired' ? 'Sign in again to keep chatting. Your conversation is kept.' : 'It could not be reached. Try again in a moment.'}</p>
          <Button size="sm" variant="outline" className="border-destructive/40 text-foreground" onClick={error === 'session_expired' ? onSignIn : () => window.location.reload()}>
            {error === 'session_expired' ? 'Sign in again' : 'Try again'}
          </Button>
        </AlertDescription>
      </Alert>
    </div>
  ) : (
    <ChatConversation className="max-w-none px-3 py-4">
      {messages.length === 0 && (
        <div className="flex flex-col gap-3 pt-6" data-testid="embed-welcome">
          <p className="text-sm">
            Hi {person.name.split(' ')[0]}, I&apos;m {agentName}.
          </p>
          {suggestions.length > 0 && (
            <div className="flex flex-col items-start gap-2" data-testid="embed-suggestions">
              {suggestions.map((s) => (
                <Button key={s} size="sm" variant="outline" className="h-auto rounded-full py-1.5 text-left font-normal whitespace-normal" onClick={() => void send(s)}>
                  {s}
                </Button>
              ))}
            </div>
          )}
        </div>
      )}
      {messages.map((m) => {
        const isLive = !!live && m.id === live.assistant.id;
        if (m.role === 'user') return <UserMessage key={m.id} message={m} disabled />;
        return (
          <AssistantMessage
            key={m.id}
            message={m}
            streaming={isLive && streaming && !!m.content}
            phaseLabel={isLive && streaming && !m.content ? 'Thinking…' : undefined}
            readOnly={isLive}
            onOpenDocument={() => undefined}
            onCopy={(text) => void navigator.clipboard.writeText(text)}
            onReply={streaming ? undefined : (text) => void send(text)}
            budgetCard={
              m.budget &&
              threadId && <BudgetCard pause={m.budget} canContinue canRaise={false} onAnswer={async (answer) => void (await budget.mutateAsync({ threadId, answer }))} />
            }
          />
        );
      })}
      {failed && (
        <SendFailedAlert
          message={failed.message}
          onRetry={() => {
            if (threadId && live?.failed) chat.dismiss(threadId);
            void send(failed.text);
          }}
          onDismiss={() => (notSent ? setNotSent(null) : threadId && chat.dismiss(threadId))}
        />
      )}
    </ChatConversation>
  );

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground" data-testid="embed-chat">
      <header className="flex items-center gap-3 border-b px-4 py-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Bot className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">{agentName}</div>
          <div className="truncate text-xs text-muted-foreground">{streaming ? 'Typing…' : 'Assistant'}</div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Chat menu" disabled={!person}>
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onThread(undefined)} data-testid="embed-new-conversation">
              <RotateCcw className="size-4" /> New conversation
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button variant="ghost" size="icon" aria-label="Close chat" onClick={onClose}>
          <X className="size-4" />
        </Button>
      </header>
      {body}
      {person && !error && (
        <div className="border-t p-3">
          <Composer canAttach={false} placeholder={`Message ${agentName}…`} streaming={streaming} onStop={() => threadId && chat.stop(threadId)} onSend={(text) => void send(text)} />
        </div>
      )}
      <footer className="px-4 pb-2 text-center text-[11px] text-muted-foreground" data-testid="embed-footer">
        {person ? `Signed in as ${person.name}. Actions wait for approval.` : 'Ops AI'}
      </footer>
    </div>
  );
}
