'use client';

import * as React from 'react';
import { Database, Paperclip, Plus, Slash, X } from 'lucide-react';

import { missingInputs, type PickedSkill, SkillChip, SkillInputsDialog, SkillMenu, toPick } from '@/components/chat/skill-menu';
import { KbDot } from '@/components/knowledge/knowledge-meta';
import { CaretMenu, type MenuRow } from '@/components/shared/caret-menu';
import { ChatPrompt } from '@/components/shared/chat-blocks';
import { AddDocumentsDialog } from '@/components/shared/add-documents-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useFileDetails } from '@/hooks/file-queries';
import { chatAgentOptions, useOptionSearch } from '@/hooks/options-queries';
import { useKnowledgeBaseSearch } from '@/hooks/knowledge-queries';
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
/** `oneLine`: the chips stay on one line and scroll sideways, for a header that has one line for them. */
/**
 * `kbs` names the chips (the ones the page looked up by id). `within` is the agent's own list of ids: the menu searches
 * only those on the server, and an agent that holds none offers none. Left out, the menu searches every knowledge base
 * the person can read.
 */
export function KbChips({ kbs, within, value, onChange, disabled, agentName, oneLine = false }: { kbs: KbOption[]; within?: string[]; value: string[]; onChange: (ids: string[]) => void; disabled?: boolean; agentName?: string; oneLine?: boolean }) {
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
            <div className="border-b px-3 py-2 text-xs font-medium">{within && agentName ? `${agentName} can answer from` : 'Answer from these knowledge bases'}</div>
            <KbMenu within={within} agentName={agentName} value={value} onChange={onChange} />
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}

function KbMenu({ within, agentName, value, onChange }: { within?: string[]; agentName?: string; value: string[]; onChange: (ids: string[]) => void }) {
  const [search, setSearch] = React.useState('');
  const found = useKnowledgeBaseSearch(search, true, within);
  const list = found.data ?? [];
  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);
  return (
    <Command shouldFilter={false}>
      <CommandInput value={search} onValueChange={setSearch} placeholder="Search knowledge bases" />
      <CommandList className="max-h-64">
        <CommandEmpty>{found.isFetching ? 'Searching…' : within?.length === 0 ? `${agentName ?? 'This agent'} has no knowledge bases. A builder adds them on its page.` : 'No knowledge bases match.'}</CommandEmpty>
        <CommandGroup>
          {list.map((k) => {
            const on = value.includes(k.id);
            return (
              <CommandItem key={k.id} value={k.name} onSelect={() => toggle(k.id)} aria-checked={on} role="menuitemcheckbox">
                <Checkbox checked={on} tabIndex={-1} aria-hidden />
                <KbDot color={k.color} />
                <span className="truncate">{k.name}</span>
              </CommandItem>
            );
          })}
        </CommandGroup>
      </CommandList>
    </Command>
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
  mentionExcept,
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
  /**
   * With it, @ searches the agents the person may chat with on the server (hooks/options-queries.ts); choosing one
   * calls it and removes the @name from the text.
   */
  onMention?: (agent: MentionOption) => void;
  /** The agent that has the chat, left out of the @ list. */
  mentionExcept?: string;
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
  // Files for the next message, uploaded or picked from Files in the Attach dialog.
  const [files, setFiles] = React.useState<ChatAttachment[]>([]);
  const [attaching, setAttaching] = React.useState(false);
  const [adding, setAdding] = React.useState(false);
  const fileDetails = useFileDetails();
  const attach = async (ids: string[]) => {
    setAdding(true);
    try {
      const found = await fileDetails(ids.filter((id) => !files.some((f) => f.fileId === id)));
      setFiles([...files, ...found.map((f) => ({ fileId: f.id, name: f.name, size: f.size }))]);
      setAttaching(false);
    } finally {
      setAdding(false);
    }
  };
  // The skill picked for the next message, shown as a chip; `filling` while the dialog asks for its missing inputs.
  const [skill, setSkill] = React.useState<PickedSkill | null>(null);
  const [filling, setFilling] = React.useState(false);
  React.useEffect(() => {
    setSkill(null);
    setFilling(false);
  }, [draftKey, skillsFor?.id]);
  const tooLong = text.length > MAX;
  const canSend = !disabledReason && !streaming && (!!text.trim() || !!skill) && !tooLong && !filling;
  const slash = skillsFor && !filling ? SLASH.exec(text) : null;
  const pickSkill = (p: PickedSkill) => {
    setText(text.replace(SLASH, '$1').trimEnd());
    setSkill(p);
  };
  const typed = onMention && !slash ? MENTION.exec(text) : null;
  const found = useOptionSearch(chatAgentOptions, typed?.[2] ?? '', !!typed);
  const matches = React.useMemo<MenuRow<MentionOption>[]>(
    () =>
      (found.data?.pages ?? [])
        .flatMap((p) => p.data)
        .filter((o) => o.id !== mentionExcept)
        .map((o) => ({ key: o.id, label: o.label, trailing: o.hint, pick: { id: o.id, name: o.label, role: o.hint ?? '' } })),
    [found.data, mentionExcept],
  );
  const [active, setActive] = React.useState('');
  React.useEffect(() => {
    if (!matches.some((r) => r.key === active)) setActive(matches[0]?.key ?? '');
  }, [matches, active]);
  const loadMore = React.useCallback(() => {
    if (found.hasNextPage && !found.isFetchingNextPage) void found.fetchNextPage();
  }, [found]);
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
  // The caret stays in the text while the @ list is open, so the text's arrow keys, Enter and Escape drive the list,
  // caught before the prompt's own Enter sends the message.
  const mentionKeys = (e: React.KeyboardEvent) => {
    if (!typed || !(e.target instanceof HTMLTextAreaElement)) return;
    const i = matches.findIndex((r) => r.key === active);
    const go = (key: string | undefined) => (e.preventDefault(), e.stopPropagation(), key !== undefined && setActive(key));
    if (e.key === 'ArrowDown' && matches.length) go(matches[(i + 1) % matches.length].key);
    else if (e.key === 'ArrowUp' && matches.length) go(matches[(i - 1 + matches.length) % matches.length].key);
    else if (e.key === 'Enter' && !e.shiftKey && i >= 0) (go(undefined), mention(matches[i].pick));
    else if (e.key === 'Escape') (go(undefined), setText(text.replace(MENTION, '$1')));
  };

  const sendWith = (picked: PickedSkill | null) => {
    const attachments = files;
    // A skill sent with no words of its own asks for what the skill does.
    onSend(text.trim() || (picked ? `Use ${picked.label}.` : ''), attachments, picked ? toPick(picked) : undefined);
    setText('');
    setSkill(null);
    setFilling(false);
    setFiles([]);
  };
  // Required inputs still empty hold the send back and ask for just those.
  const send = () => {
    if (!canSend) return;
    if (skill && missingInputs(skill).length) setFilling(true);
    else sendWith(skill);
  };

  if (disabledReason)
    return <div className="rounded-lg border border-dashed bg-muted/30 px-4 py-3 text-sm text-muted-foreground">{disabledReason}</div>;

  return (
    <div ref={box} className="relative" onKeyDownCapture={mentionKeys} onKeyDown={(e) => {
        if (e.key === 'Escape' && slash) setText(text.replace(SLASH, '$1'));
        // Backspace in an empty box takes the skill off, as it would a token typed before the text.
        if (e.key === 'Backspace' && skill && !text && e.target instanceof HTMLTextAreaElement) setSkill(null);
      }}
    >
      {slash && skillsFor && <SkillMenu agentId={skillsFor.id} agentName={skillsFor.name} query={slash[2]} onPick={pickSkill} className={menuPlace} />}
      {filling && skill && (
        <SkillInputsDialog picked={skill} onCancel={() => setFilling(false)} onDone={(inputs) => sendWith({ ...skill, inputs: { ...skill.inputs, ...inputs } })} />
      )}
      {typed && (
        <CaretMenu<MentionOption>
          rect={() => box.current?.getBoundingClientRect() ?? null}
          label="Hand this chat to"
          status={found.isPending ? 'loading' : found.isError ? 'error' : 'ready'}
          sections={matches.length ? [{ label: 'Hand this chat to', rows: matches }] : []}
          active={active}
          onActive={setActive}
          onPick={(r) => mention(r.pick)}
          onDismiss={() => setText(text.replace(MENTION, '$1'))}
          empty={`No agent called “${typed[2]}” you can chat with.`}
          error="Couldn’t load the agents. What you typed is kept; try again in a moment."
          id="chat-mention-list"
          onEnd={loadMore}
          loadingMore={found.isFetchingNextPage}
        />
      )}
    {canAttach && (
      <AddDocumentsDialog
        open={attaching}
        onOpenChange={setAttaching}
        title="Attach files"
        description="Upload new files, or pick ones already in Files. The agent reads them with this message."
        purpose="chat_attachment"
        noun="file"
        isPending={adding}
        onSubmit={attach}
      />
    )}
    <ChatPrompt
      header={
        (skill || files.length > 0) && (
          <>
            {skill && <SkillChip label={skill.label} onRemove={() => setSkill(null)} />}
            {files.map((f) => (
              <span key={f.fileId} className="inline-flex h-6 max-w-60 items-center gap-1 rounded-md border bg-muted/40 pr-1 pl-1.5 text-xs" data-testid="chat-attached-file">
                <Paperclip className="size-3 shrink-0 text-muted-foreground" />
                <span className="truncate">{f.name}</span>
                <Button type="button" variant="ghost" size="icon" className="size-4 rounded-full" onClick={() => setFiles(files.filter((x) => x.fileId !== f.fileId))} aria-label={`Remove ${f.name}`}>
                  <X className="size-3" />
                </Button>
              </span>
            ))}
          </>
        )
      }
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
          {canAttach && (
            <Button type="button" variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs" onClick={() => setAttaching(true)} aria-label="Attach files" data-testid="chat-attach">
              <Paperclip className="size-3.5" /> Attach
            </Button>
          )}
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
