'use client';

import * as React from 'react';
import { ArrowUp, Database, Plus, Square, X } from 'lucide-react';

import { KbDot } from '@/components/knowledge/knowledge-meta';
import { FileUpload, type UploadItem, uploadsBlocker } from '@/components/shared/file-upload';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Textarea } from '@/components/ui/textarea';
import type { ChatAttachment } from '@/lib/types/chat';

const MAX = 8000;

export interface KbOption {
  id: string;
  name: string;
  color: string;
}

/** The knowledge bases a conversation grounds its answers in, as removable chips plus an Add menu. */
export function KbChips({ kbs, value, onChange, disabled }: { kbs: KbOption[]; value: string[]; onChange: (ids: string[]) => void; disabled?: boolean }) {
  const selected = value.map((id) => kbs.find((k) => k.id === id) ?? { id, name: id, color: 'slate' });
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {selected.map((k) => (
        <span key={k.id} className="inline-flex h-6 items-center gap-1.5 rounded-full border bg-background pr-1 pl-2 text-xs">
          <KbDot color={k.color} className="size-2" />
          <span className="max-w-40 truncate">{k.name}</span>
          {!disabled && (
            <button type="button" className="rounded-full p-0.5 hover:bg-accent" onClick={() => onChange(value.filter((v) => v !== k.id))} aria-label={`Remove ${k.name}`}>
              <X className="size-3" />
            </button>
          )}
        </span>
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
            <div className="border-b px-3 py-2 text-xs font-medium">Answer from these knowledge bases</div>
            {kbs.length === 0 ? (
              <p className="px-3 py-4 text-xs text-muted-foreground">No knowledge bases you can read.</p>
            ) : (
              <ul className="max-h-64 overflow-y-auto py-1">
                {kbs.map((k) => {
                  const on = value.includes(k.id);
                  return (
                    <li key={k.id}>
                      <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-accent">
                        <Checkbox checked={on} onCheckedChange={(c) => onChange(c ? [...value, k.id] : value.filter((v) => v !== k.id))} />
                        <KbDot color={k.color} />
                        <span className="truncate">{k.name}</span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}

export function Composer({
  onSend,
  streaming,
  onStop,
  disabledReason,
  placeholder,
  footer,
  autoFocus,
}: {
  onSend: (text: string, attachments: ChatAttachment[]) => void;
  streaming: boolean;
  onStop: () => void;
  /** When set, the composer is read-only and says why. */
  disabledReason?: React.ReactNode;
  placeholder: string;
  footer?: React.ReactNode;
  autoFocus?: boolean;
}) {
  const [text, setText] = React.useState('');
  const [files, setFiles] = React.useState<UploadItem[]>([]);
  // Remounting the upload control clears it after a send.
  const [uploadKey, setUploadKey] = React.useState(0);
  const tooLong = text.length > MAX;
  const waiting = files.length ? uploadsBlocker(files) : undefined;
  const canSend = !disabledReason && !streaming && !!text.trim() && !tooLong && !waiting;

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
    <div className="rounded-lg border bg-background shadow-xs focus-within:ring-[3px] focus-within:ring-ring/30">
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            send();
          }
        }}
        rows={2}
        autoFocus={autoFocus}
        placeholder={placeholder}
        aria-label="Message"
        className="max-h-48 min-h-[56px] resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
      />
      <div className="flex flex-wrap items-center gap-1.5 px-2 pb-2">
        <FileUpload key={uploadKey} variant="compact" purpose="chat_attachment" multiple onChange={setFiles} id="chat-attach" testId="chat-attach" />
        {footer}
        <span className="ml-auto flex items-center gap-2">
          {waiting && <span className="text-xs text-muted-foreground">{waiting}</span>}
          {tooLong && (
            <span className="text-xs tabular-nums text-destructive">
              {text.length.toLocaleString('en-CA')} / {MAX.toLocaleString('en-CA')}
            </span>
          )}
          {streaming ? (
            <Button size="sm" variant="outline" className="h-7" onClick={onStop}>
              <Square className="size-3 fill-current" /> Stop
            </Button>
          ) : (
            <Button size="icon" className="size-7" onClick={send} disabled={!canSend} aria-label="Send">
              <ArrowUp className="size-4" />
            </Button>
          )}
        </span>
      </div>
    </div>
  );
}
