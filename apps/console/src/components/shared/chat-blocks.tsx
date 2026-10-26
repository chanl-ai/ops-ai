'use client';

import * as React from 'react';
import type { ToolUIPart } from 'ai';
import { defaultComponents, defaultRehypePlugins, type StreamdownProps } from 'streamdown';

import { Conversation, ConversationContent, ConversationScrollButton } from '@/components/ai-elements/conversation';
import { Message, MessageAction, MessageActions, MessageContent, MessageResponse } from '@/components/ai-elements/message';
import { PromptInput, PromptInputFooter, PromptInputSubmit, PromptInputTextarea, PromptInputTools } from '@/components/ai-elements/prompt-input';
import { Shimmer } from '@/components/ai-elements/shimmer';
import { Tool, ToolContent, ToolHeader, ToolInput, ToolOutput } from '@/components/ai-elements/tool';
import { cn } from '@/lib/utils';

// The chat surface's AI Elements blocks, wrapped once so pages and chat components never import components/ai-elements
// directly (docs/console/standards.md: compose registry blocks behind components/shared).

/** The scrolling message list: sticks to the newest message while it streams, with a jump-to-latest button. */
export function ChatConversation({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <Conversation className="min-h-0 flex-1">
      <ConversationContent className={cn('mx-auto w-full max-w-3xl gap-5 px-4 py-5', className)}>{children}</ConversationContent>
      <ConversationScrollButton aria-label="Jump to the newest reply" />
    </Conversation>
  );
}

/** One message: a bubble for the person, open text for the agent, with its actions underneath. */
export function ChatBubble({ from, children, actions, className }: { from: 'user' | 'assistant'; children: React.ReactNode; actions?: React.ReactNode; className?: string }) {
  return (
    <Message from={from} className={cn(from === 'assistant' && 'max-w-full', className)}>
      <MessageContent className={cn(from === 'user' && 'whitespace-pre-wrap', from === 'assistant' && 'w-full')}>{children}</MessageContent>
      {actions && <MessageActions className={cn('opacity-100 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:focus-within:opacity-100', from === 'user' && 'justify-end')}>{actions}</MessageActions>}
    </Message>
  );
}

/** An icon action under a message, with a tooltip naming it. */
export function ChatAction({ label, onClick, active, children }: { label: string; onClick: () => void; active?: boolean; children: React.ReactNode }) {
  return (
    <MessageAction tooltip={label} label={label} onClick={onClick} aria-pressed={active} className={cn('size-7', active && 'bg-accent text-foreground')}>
      {children}
    </MessageAction>
  );
}

/** What the agent is doing before any text arrives, e.g. "Searching Card disputes". */
export function ChatThinking({ label }: { label: string }) {
  return (
    <div role="status" className="py-1 text-xs">
      <Shimmer as="span">{label}</Shimmer>
    </div>
  );
}

// Citation markers ([1] or [^1]) become links to #cite-n, which the link renderer swaps for the caller's citation.
const CITE = /\s?\[\^?(\d+)\]/g;
const CITE_HREF = /^#cite-(\d+)$/;

// Replies can carry text from documents and tool results the model read, so markdown in them is not trusted: an
// image would load from its host on render, with no click, and could carry what the model saw in its URL. Images are
// never fetched: harden allows no image prefix and puts "[Image blocked: alt]" in its place, and the img renderer, a
// second guard, draws no source. Links keep Streamdown's link-safety confirmation before they open.
type PluggableList = NonNullable<StreamdownProps['rehypePlugins']>;
type Pluggable = PluggableList[number];
const { harden: hardenPlugin, ...otherRehype } = defaultRehypePlugins;
const [harden, hardenOptions] = hardenPlugin as [Pluggable, Record<string, unknown>];
const REHYPE = [...Object.values(otherRehype), [harden, { ...hardenOptions, allowedImagePrefixes: [], allowDataImages: false, blockedImageClass: 'inline-block rounded border border-dashed px-1.5 py-0.5 text-xs text-muted-foreground' }]] as PluggableList;
const DefaultLink = defaultComponents.a;

function BlockedImage({ alt }: React.ComponentProps<'img'>) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-dashed px-1.5 py-0.5 text-xs text-muted-foreground" data-testid="blocked-image">
      Image not shown{alt ? `: ${alt}` : ''}
    </span>
  );
}

/**
 * The agent's reply as markdown, streamed. `renderCitation` draws each [n] marker; a marker cut off mid-stream stays
 * hidden until it completes. MessageResponse re-renders only when its text changes, and citations arrive after the
 * text, so `citations` (their count) remounts it when they do.
 */
export function ChatResponse({ text, renderCitation, streaming, citations = 0 }: { text: string; renderCitation: (n: number) => React.ReactNode; streaming?: boolean; citations?: number }) {
  const src = (streaming ? text.replace(/\s*\[\^?\d*$/, '') : text).replace(CITE, (_, n: string) => ` [${n}](#cite-${n})`);
  const components = React.useMemo(
    () => ({
      a: (props: React.ComponentProps<typeof DefaultLink>) => {
        const cite = props.href?.match(CITE_HREF);
        return cite ? <>{renderCitation(Number(cite[1]))}</> : <DefaultLink {...props} />;
      },
      img: BlockedImage,
    }),
    [renderCitation],
  );
  return (
    <MessageResponse key={citations} className="text-sm leading-relaxed" components={components} rehypePlugins={REHYPE} isAnimating={streaming}>
      {src}
    </MessageResponse>
  );
}

export type ChatToolState = 'running' | 'success' | 'failed' | 'gated';

const TOOL_STATE: Record<ChatToolState, ToolUIPart['state']> = {
  running: 'input-available',
  success: 'output-available',
  failed: 'output-error',
  gated: 'approval-requested',
};

/** One tool call: its name and state on one line, open to show the input and the output. */
export function ChatToolCall({ name, state, input, output, error, detail }: { name: string; state: ChatToolState; input: unknown; output?: unknown; error?: string; detail?: React.ReactNode }) {
  return (
    <Tool className="mb-0 bg-muted/30" data-testid="chat-tool-call" data-state={state}>
      <ToolHeader title={name} type={`tool-${name}`} state={TOOL_STATE[state]} className="p-2 [&_span]:text-xs" />
      <ToolContent>
        {detail && <div className="px-4 pt-3 text-xs text-muted-foreground">{detail}</div>}
        <ToolInput input={input} />
        {state === 'running' ? <p className="px-4 pb-4 text-xs text-muted-foreground">Waiting for the tool to return…</p> : <ToolOutput output={output as ToolUIPart['output']} errorText={error} />}
      </ToolContent>
    </Tool>
  );
}

/**
 * The message box on AI Elements' PromptInput: Enter sends, Shift+Enter breaks a line. Attachments go through the
 * Files API in `tools`, never through the block's own file handling.
 */
export function ChatPrompt({
  value,
  onChange,
  onSubmit,
  canSubmit,
  streaming,
  onStop,
  placeholder,
  autoFocus,
  tools,
  status,
}: {
  value: string;
  onChange: (text: string) => void;
  onSubmit: () => void;
  canSubmit: boolean;
  streaming: boolean;
  onStop: () => void;
  placeholder: string;
  autoFocus?: boolean;
  /** Left of the send button: attach, knowledge and the like. */
  tools?: React.ReactNode;
  /** Right of the tools, e.g. a length warning. */
  status?: React.ReactNode;
}) {
  return (
    <PromptInput
      onSubmit={() => {
        if (streaming) onStop();
        else if (canSubmit) onSubmit();
      }}
    >
      <PromptInputTextarea value={value} onChange={(e) => onChange(e.currentTarget.value)} placeholder={placeholder} autoFocus={autoFocus} aria-label="Message" className="max-h-48 min-h-14" />
      <PromptInputFooter>
        <PromptInputTools className="flex-wrap">{tools}</PromptInputTools>
        <span className="ml-auto flex items-center gap-2">
          {status}
          <PromptInputSubmit status={streaming ? 'streaming' : undefined} disabled={!streaming && !canSubmit} aria-label={streaming ? 'Stop' : 'Send'} />
        </span>
      </PromptInputFooter>
    </PromptInput>
  );
}
