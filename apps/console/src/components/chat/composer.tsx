'use client';

import * as React from 'react';
import { Database, Plus, X } from 'lucide-react';

import { KbDot } from '@/components/knowledge/knowledge-meta';
import { ChatPrompt } from '@/components/shared/chat-blocks';
import { FileUpload, type UploadItem, uploadsBlocker } from '@/components/shared/file-upload';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Command, CommandEmpty, CommandGroup, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useAttachChatFile } from '@/hooks/chat-settings-queries';
import type { ChatAttachment } from '@/lib/types/chat';

const MAX = 8000;

export interface KbOption {
  id: string;
  name: string;
  color: string;
}

/** The knowledge bases a conversation grounds its answers in, as removable chips plus an Add menu. */
/**
 * The knowledge an answer may use. `agentName` names the agent whose allowed bases `kbs` are, so an empty list says the
 * agent holds none and where they are added, rather than suggesting the person can read none (UX knowledge-5).
 */
export function KbChips({ kbs, value, onChange, disabled, agentName }: { kbs: KbOption[]; value: string[]; onChange: (ids: string[]) => void; disabled?: boolean; agentName?: string }) {
  const selected = value.map((id) => kbs.find((k) => k.id === id) ?? { id, name: id, color: 'slate' });
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {selected.map((k) => (
        <Badge key={k.id} variant="outline" className="h-6 gap-1.5 rounded-full bg-background pr-1 pl-2 font-normal">
          <KbDot color={k.color} className="size-2" />
          <span className="max-w-40 truncate">{k.name}</span>
          {!disabled && (
            <Button type="button" variant="ghost" size="icon" className="size-4 rounded-full" onClick={() => onChange(value.filter((v) => v !== k.id))} aria-label={`Remove ${k.name}`}>
              <X className="size-3" />
            </Button>
          )}
        </Badge>
      ))}
      {!disabled && (
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm" className="h-6 gap-1 rounded-full px-2 text-xs">
              {value.length ? <Plus className="size-3" /> : <Database className="size-3" />}
              {value.length ? 'Knowledge' : 'Add knowledge'}
            </Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-72 p-0">
            <div className="border-b px-3 py-2 text-xs font-medium">{agentName ? `${agentName} can answer from` : 'Answer from these knowledge bases'}</div>
            <Command>
              <CommandList className="max-h-64">
                <CommandEmpty>{agentName ? `${agentName} has no knowledge bases. A builder adds them on its page.` : 'No knowledge bases you can read.'}</CommandEmpty>
                <CommandGroup>
                  {kbs.map((k) => {
                    const on = value.includes(k.id);
                    return (
                      <CommandItem key={k.id} value={k.name} onSelect={() => onChange(on ? value.filter((v) => v !== k.id) : [...value, k.id])} aria-checked={on} role="menuitemcheckbox">
                        <Checkbox checked={on} tabIndex={-1} aria-hidden />
                        <KbDot color={k.color} />
                        <span className="truncate">{k.name}</span>
                      </CommandItem>
                    );
                  })}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}

// What chat reads (agents-service activities/attachments.py); the server refuses anything else with 422.
const CHAT_FILE_TYPES = ['pdf', 'txt', 'md', 'csv', 'docx'];

/** An agent the person can hand the chat to by typing @ (c-174). */
export interface MentionOption {
  id: string;
  name: string;
  role: string;
}

// "@" at the start or after a space, then the name typed so far, at the end of the text.
const MENTION = /(^|\s)@([\w-]*)$/;

export function Composer({
  onSend,
  streaming,
  onStop,
  disabledReason,
  placeholder,
  footer,
  autoFocus,
  canAttach = true,
  mentions,
  onMention,
}: {
  onSend: (text: string, attachments: ChatAttachment[]) => void;
  streaming: boolean;
  onStop: () => void;
  /** When set, the composer is read-only and says why. */
  disabledReason?: React.ReactNode;
  placeholder: string;
  footer?: React.ReactNode;
  autoFocus?: boolean;
  /** False where attachments have no route, as in the embedded chat (c-158). */
  canAttach?: boolean;
  /** Agents offered after @; choosing one calls `onMention` and removes the @name from the text. */
  mentions?: MentionOption[];
  onMention?: (agent: MentionOption) => void;
}) {
  const [text, setText] = React.useState('');
  const attach = useAttachChatFile();
  const [files, setFiles] = React.useState<UploadItem[]>([]);
  // Remounting the upload control clears it after a send.
  const [uploadKey, setUploadKey] = React.useState(0);
  const tooLong = text.length > MAX;
  const waiting = files.length ? uploadsBlocker(files) : undefined;
  const canSend = !disabledReason && !streaming && !!text.trim() && !tooLong && !waiting;
  const typed = mentions?.length && onMention ? MENTION.exec(text) : null;
  const matches = typed ? mentions!.filter((a) => a.name.toLowerCase().includes(typed[2].toLowerCase())) : [];
  const mention = (a: MentionOption) => {
    setText(text.replace(MENTION, '$1').trimEnd());
    onMention!(a);
  };

  const send = () => {
    if (!canSend) return;
    const attachments: ChatAttachment[] = files.flatMap((f) => (f.fileId ? [{ fileId: f.fileId, name: f.name, size: f.size }] : []));
    onSend(text.trim(), attachments);
    setText('');
    setFiles([]);
    setUploadKey((k) => k + 1);
  };

  if (disabledReason)
    return <div className="rounded-lg border border-dashed bg-muted/30 px-4 py-3 text-sm text-muted-foreground">{disabledReason}</div>;

  return (
    <div className="relative">
      {typed && (
        <div className="absolute inset-x-0 bottom-full z-10 mb-2 overflow-hidden rounded-lg border bg-popover shadow-md" data-testid="mention-list">
          <Command shouldFilter={false}>
            <CommandList className="max-h-56">
              <CommandEmpty>No agent called “{typed[2]}” you can chat with.</CommandEmpty>
              <CommandGroup heading="Hand this chat to">
                {matches.map((a) => (
                  <CommandItem key={a.id} value={a.id} onSelect={() => mention(a)}>
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-medium">{a.name}</span>
                      <span className="truncate text-xs text-muted-foreground">{a.role}</span>
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </div>
      )}
    <ChatPrompt
      value={text}
      onChange={setText}
      onSubmit={send}
      canSubmit={canSend}
      streaming={streaming}
      onStop={onStop}
      placeholder={placeholder}
      autoFocus={autoFocus}
      tools={
        <>
          {canAttach && <FileUpload key={uploadKey} variant="compact" purpose="chat_attachment" multiple onChange={setFiles} id="chat-attach" testId="chat-attach" types={CHAT_FILE_TYPES} upload={attach} />}
          {footer}
        </>
      }
      status={
        <>
          {waiting && <span className="text-xs text-muted-foreground">{waiting}</span>}
          {tooLong && (
            <span className="text-xs tabular-nums text-destructive">
              {text.length.toLocaleString('en-CA')} / {MAX.toLocaleString('en-CA')}
            </span>
          )}
        </>
      }
    />
    </div>
  );
}
