'use client';

import * as React from 'react';
import { Database, Plus, Slash, X } from 'lucide-react';

import { type PickedSkill, SkillChip, SkillInputsForm, SkillMenu, toPick } from '@/components/chat/skill-menu';
import { KbDot } from '@/components/knowledge/knowledge-meta';
import { ChatPrompt } from '@/components/shared/chat-blocks';
import { FileUpload, type UploadItem, uploadsBlocker } from '@/components/shared/file-upload';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Command, CommandEmpty, CommandGroup, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { ChatAttachment, SkillPick } from '@/lib/types/chat';
import { cn } from '@/lib/utils';

const MAX = 8000;
/** Height the / and @ menus need above the composer; with less room they open below it. */
const MENU_ROOM = 340;

/** Room between `el` and the top of the area it scrolls in, which ends at that area's header. */
function roomAbove(el: HTMLElement): number {
  let p = el.parentElement;
  while (p && !/(auto|scroll)/.test(getComputedStyle(p).overflowY)) p = p.parentElement;
  return el.getBoundingClientRect().top - (p ? p.getBoundingClientRect().top : 0);
}

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
/** `oneLine`: the chips stay on one line and scroll sideways, for a header that has one line for them. */
export function KbChips({ kbs, value, onChange, disabled, agentName, oneLine = false }: { kbs: KbOption[]; value: string[]; onChange: (ids: string[]) => void; disabled?: boolean; agentName?: string; oneLine?: boolean }) {
  const selected = value.map((id) => kbs.find((k) => k.id === id) ?? { id, name: id, color: 'slate' });
  return (
    <div className={cn('flex items-center gap-1.5', oneLine ? 'min-w-0 overflow-x-auto [scrollbar-width:none] [&>*]:shrink-0' : 'flex-wrap')}>
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
            <Button variant="outline" size="sm" className="h-6 gap-1 rounded-full px-2 text-xs" aria-label={value.length ? 'Knowledge' : 'Add knowledge'}>
              {value.length ? <Plus className="size-3" /> : <Database className="size-3" />}
              {/* On one header line at phone width the words would be cut; the icon stays, named for screen readers. */}
              <span className={cn(oneLine && 'max-sm:sr-only')}>{value.length ? 'Knowledge' : 'Add knowledge'}</span>
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

/** An agent the person can hand the chat to by typing @. */
export interface MentionOption {
  id: string;
  name: string;
  role: string;
}

// "@" at the start or after a space, then the name typed so far, at the end of the text.
const MENTION = /(^|\s)@([\w-]*)$/;
// "/" at the start or after a space, then the skill searched for so far, at the end of the text.
const SLASH = /(^|\s)\/([^\s/]*)$/;

// A chat's unsent draft, kept in this tab only, so signing in again after the session ends brings it back.
const DRAFT = 'ops.chat.draft.';
const readDraft = (key?: string) => {
  if (!key) return '';
  try {
    return window.sessionStorage.getItem(DRAFT + key) ?? '';
  } catch {
    return '';
  }
};
const writeDraft = (key: string | undefined, text: string) => {
  if (!key) return;
  try {
    if (text) window.sessionStorage.setItem(DRAFT + key, text);
    else window.sessionStorage.removeItem(DRAFT + key);
  } catch {
    // No storage: the draft lasts until the page goes, as before.
  }
};

/** Forgets every kept draft; signing out calls it, so a shared machine never shows the last person's words. */
export function clearChatDrafts() {
  try {
    for (const k of Object.keys(window.sessionStorage)) if (k.startsWith(DRAFT)) window.sessionStorage.removeItem(k);
  } catch {
    // No storage, nothing kept.
  }
}

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
  draftKey,
  skillsFor,
}: {
  onSend: (text: string, attachments: ChatAttachment[], skill?: SkillPick) => void;
  streaming: boolean;
  onStop: () => void;
  /** When set, the composer is read-only and says why. */
  disabledReason?: React.ReactNode;
  placeholder: string;
  footer?: React.ReactNode;
  autoFocus?: boolean;
  /** False where attachments have no route, as in the embedded chat. */
  canAttach?: boolean;
  /** Agents offered after @; choosing one calls `onMention` and removes the @name from the text. */
  mentions?: MentionOption[];
  onMention?: (agent: MentionOption) => void;
  /** Keeps the unsent text under this key for the tab (the chat's id, or "new" on Chat's home). */
  draftKey?: string;
  /** The agent whose skills / offers; without it / is plain text. */
  skillsFor?: { id: string; name: string };
}) {
  const [text, setTextState] = React.useState('');
  React.useEffect(() => {
    setTextState(readDraft(draftKey));
  }, [draftKey]);
  const setText = (next: string) => {
    setTextState(next);
    writeDraft(draftKey, next);
  };
  const [files, setFiles] = React.useState<UploadItem[]>([]);
  // Remounting the upload control clears it after a send.
  const [uploadKey, setUploadKey] = React.useState(0);
  // The skill picked for the next message; `filling` while its inputs form is open.
  const [skill, setSkill] = React.useState<PickedSkill | null>(null);
  const [filling, setFilling] = React.useState<PickedSkill | null>(null);
  React.useEffect(() => {
    setSkill(null);
    setFilling(null);
  }, [draftKey, skillsFor?.id]);
  const tooLong = text.length > MAX;
  const waiting = files.length ? uploadsBlocker(files) : undefined;
  const canSend = !disabledReason && !streaming && (!!text.trim() || !!skill) && !tooLong && !waiting && !filling;
  const slash = skillsFor && !filling ? SLASH.exec(text) : null;
  const pickSkill = (p: PickedSkill) => {
    setText(text.replace(SLASH, '$1').trimEnd());
    if (p.fields.length) setFilling(p);
    else setSkill(p);
  };
  const typed = mentions?.length && onMention && !slash ? MENTION.exec(text) : null;
  const matches = typed ? mentions!.filter((a) => a.name.toLowerCase().includes(typed[2].toLowerCase())) : [];
  // The menus open above the composer, unless it sits near the top (Chat's home), where they would run under the header.
  const box = React.useRef<HTMLDivElement>(null);
  const [below, setBelow] = React.useState(false);
  const menuOpen = !!slash || !!typed;
  React.useLayoutEffect(() => {
    if (menuOpen && box.current) setBelow(roomAbove(box.current) < MENU_ROOM);
  }, [menuOpen]);
  const menuPlace = below ? 'top-full mt-2' : 'bottom-full mb-2';
  const mention = (a: MentionOption) => {
    setText(text.replace(MENTION, '$1').trimEnd());
    onMention!(a);
  };

  const send = () => {
    if (!canSend) return;
    const attachments: ChatAttachment[] = files.flatMap((f) => (f.fileId ? [{ fileId: f.fileId, name: f.name, size: f.size }] : []));
    // A skill sent with no words of its own asks for what the skill does.
    onSend(text.trim() || (skill ? `Use ${skill.label}.` : ''), attachments, skill ? toPick(skill) : undefined);
    setText('');
    setSkill(null);
    setFiles([]);
    setUploadKey((k) => k + 1);
  };

  if (disabledReason)
    return <div className="rounded-lg border border-dashed bg-muted/30 px-4 py-3 text-sm text-muted-foreground">{disabledReason}</div>;

  return (
    <div ref={box} className="relative" onKeyDown={(e) => e.key === 'Escape' && slash && setText(text.replace(SLASH, '$1'))}>
      {slash && skillsFor && <SkillMenu agentId={skillsFor.id} agentName={skillsFor.name} query={slash[2]} onPick={pickSkill} className={menuPlace} />}
      {filling && (
        <SkillInputsForm
          picked={filling}
          onBack={() => setFilling(null)}
          onDone={(inputs) => {
            setSkill({ ...filling, inputs });
            setFilling(null);
          }}
        />
      )}
      {skill && (
        <div className="mb-2 flex">
          <SkillChip label={skill.label} onRemove={() => setSkill(null)} />
        </div>
      )}
      {typed && (
        <div className={cn('absolute inset-x-0 z-10 overflow-hidden rounded-lg border bg-popover shadow-md', menuPlace)} data-testid="mention-list">
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
          {canAttach && <FileUpload key={uploadKey} variant="compact" purpose="chat_attachment" multiple onChange={setFiles} id="chat-attach" testId="chat-attach" />}
          {skillsFor && (
            <Button type="button" variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs text-muted-foreground" onClick={() => setText(text && !/\s$/.test(text) ? `${text} /` : `${text}/`)} data-testid="chat-skills" aria-label="Pick a skill">
              <Slash className="size-3" /> Skills
            </Button>
          )}
          {footer}
        </>
      }
      status={
        <>
          {waiting && <span className="text-xs text-muted-foreground">{waiting}</span>}
          {tooLong && (
            <span className="text-xs tabular-nums text-destructive-text">
              {text.length.toLocaleString('en-CA')} / {MAX.toLocaleString('en-CA')}
            </span>
          )}
        </>
      }
    />
    </div>
  );
}
