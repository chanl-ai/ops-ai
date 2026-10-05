'use client';

import * as React from 'react';
import type { Icon as TablerIcon } from '@tabler/icons-react';
import { AlertCircle, ArrowLeft, Bot, Check, Clock, Database, Loader2, Mail, MessagesSquare, Route, Search, Users, type LucideIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator, CommandShortcut } from '@/components/ui/command';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { SearchGroup, SearchHit, SearchResults } from '@/lib/types/search';

export interface PalettePage {
  title: string;
  href: string;
  section?: string;
  icon: TablerIcon | LucideIcon;
}

export interface PaletteAction {
  id: string;
  label: string;
  icon: LucideIcon;
  /** Extra words that should find this action, e.g. "create add". */
  keywords?: string;
  /** `teams` opens the team list inside the palette instead of running. */
  opens?: 'teams';
  run?: () => void;
}

const GROUP: Record<SearchGroup, { label: string; icon: LucideIcon }> = {
  workflows: { label: 'Workflows', icon: Route },
  agents: { label: 'Agents', icon: Bot },
  cases: { label: 'Cases', icon: Mail },
  knowledge: { label: 'Knowledge bases', icon: Database },
  chats: { label: 'Chats', icon: MessagesSquare },
};

/** Top-bar trigger. Adapted from the shared component library's search command, as a labelled field so the shortcut is visible. */
export function SearchButton({ onClick }: { onClick: () => void }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="outline" size="sm" onClick={onClick} aria-label="Search (⌘K)" data-testid="header-search" className="h-8 gap-2 px-2 text-muted-foreground sm:w-56 sm:justify-start sm:px-3">
          <Search className="size-4" />
          <span className="hidden flex-1 text-left font-normal sm:inline">Search or jump to…</span>
          <kbd className="hidden rounded border bg-muted px-1.5 font-mono text-[10px] sm:inline">⌘K</kbd>
        </Button>
      </TooltipTrigger>
      <TooltipContent className="sm:hidden">
        Search <kbd className="ml-1 text-xs">⌘K</kbd>
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * ⌘K palette: pages and actions are filtered here, records come from server search. Adapted from the shared
 * component library's search command (CommandDialog, grouped items, run-then-close), with server results, recents and a team list.
 */
export function CommandPalette({
  open,
  onOpenChange,
  query,
  onQueryChange,
  pages,
  actions,
  results,
  loading,
  error,
  onRetry,
  recents,
  onOpenHit,
  onNavigate,
  teams,
  onSwitchTeam,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  query: string;
  onQueryChange: (q: string) => void;
  pages: PalettePage[];
  actions: PaletteAction[];
  results?: SearchResults;
  loading: boolean;
  error?: string;
  onRetry: () => void;
  recents: SearchHit[];
  onOpenHit: (hit: SearchHit) => void;
  onNavigate: (href: string) => void;
  teams: { id: string; name: string; current: boolean }[];
  onSwitchTeam: (id: string) => void;
}) {
  const [sub, setSub] = React.useState<'teams' | null>(null);
  React.useEffect(() => {
    if (!open) setSub(null);
  }, [open]);

  const typed = query.trim();
  // Server hits carry the current query in their value so cmdk's client filter never hides them.
  const hitValue = (h: SearchHit) => `${typed} ${h.group} ${h.title} ${h.id}`;

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Search and commands" description="Search records, open pages and run actions" className="sm:max-w-xl">
      <CommandInput
        placeholder={sub === 'teams' ? 'Switch to team…' : 'Search workflows, agents, cases, knowledge, chats…'}
        value={query}
        onValueChange={onQueryChange}
        onKeyDown={(e) => {
          if (sub && e.key === 'Backspace' && !query) setSub(null);
        }}
      />
      <CommandList className="max-h-[min(60vh,440px)]">
        {sub === 'teams' ? (
          <CommandGroup heading="Switch team">
            <CommandItem value="back" onSelect={() => setSub(null)}>
              <ArrowLeft /> Back
            </CommandItem>
            {teams.map((t) => (
              <CommandItem key={t.id} value={`team ${t.name}`} onSelect={() => onSwitchTeam(t.id)}>
                <Users />
                <span className="flex-1">{t.name}</span>
                {t.current && <Check className="size-4" aria-label="Current team" />}
              </CommandItem>
            ))}
          </CommandGroup>
        ) : (
          <>
            {!loading && <CommandEmpty>{typed ? `Nothing matches “${typed}”.` : 'Type to search.'}</CommandEmpty>}

            {/* Hits for an older query are hidden while the new one runs, so ↵ never opens a stale result. */}
            {typed && loading && (
              <div className="flex items-center gap-2 px-4 py-3 text-sm text-muted-foreground" role="status">
                <Loader2 className="size-4 animate-spin" /> Searching…
              </div>
            )}
            {typed && error && (
              <CommandGroup heading="Records">
                <CommandItem value={`${typed} retry search`} onSelect={onRetry} className="text-destructive">
                  <AlertCircle className="text-destructive" /> Search failed. Try again
                </CommandItem>
              </CommandGroup>
            )}

            {!typed && recents.length > 0 && (
              <CommandGroup heading="Recent">
                {recents.map((h) => {
                  const G = GROUP[h.group];
                  return (
                    <CommandItem key={`recent-${h.group}-${h.id}`} value={`recent ${h.title} ${h.id}`} onSelect={() => onOpenHit(h)}>
                      <Clock />
                      <span className="min-w-0 flex-1 truncate">{h.title}</span>
                      <span className="text-xs text-muted-foreground">{G.label}</span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            )}

            {typed &&
              !loading &&
              results?.groups.map((g) => {
                const G = GROUP[g.group];
                return (
                  <CommandGroup key={g.group} heading={g.total > g.hits.length ? `${G.label} · ${g.hits.length} of ${g.total}` : G.label}>
                    {g.hits.map((h) => (
                      <CommandItem key={`${h.group}-${h.id}`} value={hitValue(h)} onSelect={() => onOpenHit(h)}>
                        <G.icon />
                        <div className="min-w-0 flex-1">
                          <div className="truncate">{h.title}</div>
                          {h.detail && <div className="truncate text-xs text-muted-foreground">{h.detail}</div>}
                        </div>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                );
              })}

            <CommandGroup heading="Actions">
              {actions.map((a) => (
                <CommandItem key={a.id} value={`${a.label} ${a.keywords ?? ''}`} onSelect={() => {
                    if (a.opens !== 'teams') return a.run?.();
                    setSub('teams');
                    onQueryChange('');
                  }}>
                  <a.icon />
                  <span className="flex-1">{a.label}</span>
                  {a.opens && <CommandShortcut>›</CommandShortcut>}
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup heading="Pages">
              {pages.map((p) => (
                <CommandItem key={p.href} value={`${p.title} ${p.section ?? ''} ${p.href}`} onSelect={() => onNavigate(p.href)}>
                  <p.icon />
                  <span className="flex-1">{p.title}</span>
                  {p.section && <span className="text-xs text-muted-foreground">{p.section}</span>}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
      </CommandList>
      <div className="flex items-center gap-3 border-t px-3 py-2 text-[11px] text-muted-foreground">
        <span>↵ open</span>
        <span>↑↓ move</span>
        <span>esc close</span>
        {loading && typed && (
          <span className="ml-auto flex items-center gap-1">
            <Loader2 className="size-3 animate-spin" /> Searching
          </span>
        )}
      </div>
    </CommandDialog>
  );
}
