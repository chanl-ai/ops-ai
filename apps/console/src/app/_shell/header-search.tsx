'use client';

import * as React from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Bot, Cable, Mail, MessageSquarePlus, Route, Users } from 'lucide-react';
import { IconShieldCheck } from '@tabler/icons-react';
import { toast } from 'sonner';

import { CommandPalette, type PaletteAction, type PalettePage, SearchButton } from '@/components/header/command-palette';
import { useRecentSearches, useSearch, useVisitSearchHit } from '@/hooks/search-queries';
import { useTeam } from '@/hooks/use-team';
import { NAV } from '@/lib/nav';
import type { SearchHit } from '@/lib/types/search';

/** Sub-pages that are not in the sidebar but are worth jumping to. */
const EXTRA_PAGES: PalettePage[] = [
  { title: 'Gate policies', href: '/reviews/policies', section: 'Reviews', icon: IconShieldCheck },
];

/**
 * The ⌘K palette and its top-bar button. ⌘K / Ctrl+K opens it from anywhere, including inside chat, where
 * "New chat" is offered first.
 */
export function HeaderSearch() {
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState('');
  const search = useSearch(query, open);
  const recents = useRecentSearches(open);
  const visit = useVisitSearchHit();
  const { teams, teamId, switchTeam } = useTeam();

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey || e.key.toLowerCase() !== 'k') return;
      e.preventDefault();
      // Capture phase plus stopPropagation keeps page-level ⌘K handlers from also firing.
      e.stopPropagation();
      setOpen((o) => !o);
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, []);
  React.useEffect(() => {
    if (!open) setQuery('');
  }, [open]);

  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };
  const pages: PalettePage[] = [...NAV.flatMap((g) => g.items.map((i) => ({ title: i.title, href: i.url, section: g.label, icon: i.icon }))), ...EXTRA_PAGES];
  const newChat: PaletteAction = { id: 'new-chat', label: 'New chat', icon: MessageSquarePlus, keywords: 'ask conversation start', run: () => go('/chat') };
  const actions: PaletteAction[] = [
    ...(pathname.startsWith('/chat') ? [newChat] : []),
    { id: 'new-workflow', label: 'New workflow', icon: Route, keywords: 'create add', run: () => go('/workflows?create=1') },
    { id: 'new-agent', label: 'New agent', icon: Bot, keywords: 'create add', run: () => go('/agents?create=1') },
    { id: 'connect-system', label: 'Connect a system', icon: Cable, keywords: 'integration connection oauth sharepoint servicenow salesforce credential', run: () => go('/integrations?tab=catalog') },
    { id: 'connect-mailbox', label: 'Connect mailbox', icon: Mail, keywords: 'email inbox deployment outlook', run: () => go('/deployments?create=email') },
    ...(pathname.startsWith('/chat') ? [] : [newChat]),
    { id: 'switch-team', label: 'Switch team', icon: Users, keywords: 'team change', opens: 'teams' },
  ];

  return (
    <>
      <SearchButton onClick={() => setOpen(true)} />
      <CommandPalette
        open={open}
        onOpenChange={setOpen}
        query={query}
        onQueryChange={setQuery}
        pages={pages}
        actions={actions}
        results={search.data}
        loading={search.settling || search.isFetching}
        error={search.isError ? search.error.message : undefined}
        onRetry={() => search.refetch()}
        recents={recents.data ?? []}
        onOpenHit={(hit: SearchHit) => {
          visit.mutate(hit);
          go(hit.href);
        }}
        onNavigate={go}
        teams={teams.map((t) => ({ id: t.id, name: t.name, current: t.id === teamId }))}
        onSwitchTeam={(id) => {
          setOpen(false);
          switchTeam(id);
          toast.success(`Switched to ${teams.find((t) => t.id === id)?.name ?? 'team'}`);
        }}
      />
    </>
  );
}
