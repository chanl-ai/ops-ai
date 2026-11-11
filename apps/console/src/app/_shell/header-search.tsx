'use client';

import * as React from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Bot, Cable, Link2, Mail, MessageSquarePlus, Route, Sparkles, Users } from 'lucide-react';
import { IconShieldCheck } from '@tabler/icons-react';
import { toast } from 'sonner';

import { CommandPalette, type PaletteAction, type PalettePage, SearchButton } from '@/components/header/command-palette';
import { useConnectUrl } from '@/hooks/connect-queries';
import { useFlagged } from '@/hooks/flag-queries';
import { useNavAllows } from '@/hooks/me-queries';
import { useRecentSearches, useSearch, useVisitSearchHit } from '@/hooks/search-queries';
import { useTeam } from '@/hooks/use-team';
import { childrenOffered, itemOffered, NAV, SETTINGS_VIEW } from '@/lib/nav';
import type { NavNeed } from '@/lib/nav';
import type { FlagName } from '@/lib/types/flags';
import type { SearchHit } from '@/lib/types/search';

/** Sub-pages that are not in the sidebar but are worth jumping to; one with a `flag` shows only while the install turns it on. */
const EXTRA_PAGES: (PalettePage & { flag?: FlagName; needs?: NavNeed })[] = [
  // Connecting an assistant is the MCP channel of Deployments, so the page entry opens that tab.
  { title: 'Connect your assistant', href: '/channels/mcp', area: 'Build', section: 'Channels', icon: Link2, keywords: 'MCP URL Claude Cursor Copilot ChatGPT connect', flag: 'mcp_gateway', needs: { area: 'deployments', action: 'view' } },
  { title: 'Gate policies', href: '/settings/policies/gates', area: 'Govern', section: 'Policies', icon: IconShieldCheck, needs: SETTINGS_VIEW },
];

/**
 * The ⌘K palette and its top-bar button. ⌘K / Ctrl+K opens it from anywhere, including inside chat, where
 * "New chat" is offered first.
 */
export function HeaderSearch() {
  const router = useRouter();
  const allows = useNavAllows();
  const pathname = usePathname();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState('');
  const search = useSearch(query, open);
  const recents = useRecentSearches(open);
  const visit = useVisitSearchHit();
  const { teams, teamId, switchTeam } = useTeam();
  const connectUrl = useConnectUrl();
  const extraPages = useFlagged(EXTRA_PAGES);

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
  // Every page the person's cells open, grouped by area as the header offers them. Child routes are tabs, not sidebar
  // rows, so they are listed here to stay reachable by name. The chat entry is the New chat action below.
  const navPages: PalettePage[] = NAV.flatMap((g) =>
    g.items
      .filter((i) => i.url !== '/chat' && itemOffered(allows, i))
      .flatMap((i) => [
        { title: i.title, href: i.url, area: g.label, icon: i.icon },
        ...childrenOffered(allows, i).map((c) => ({ title: c.title, href: c.url, area: g.label, section: i.title, icon: c.icon ?? i.icon })),
      ])
  );
  const chatPages: PalettePage[] = NAV.flatMap((g) => g.items.filter((i) => i.url === '/chat' && itemOffered(allows, i)).flatMap((i) => childrenOffered(allows, i).map((c) => ({ title: c.title, href: c.url, area: g.label, section: 'Chat', icon: c.icon ?? i.icon }))));
  const allowedExtra = extraPages.filter((e) => allows(e.needs) === true);
  const pages: PalettePage[] = [...navPages, ...chatPages, ...allowedExtra.filter((e) => ![...navPages, ...chatPages].some((p) => p.href === e.href))];
  const newChat: PaletteAction = { id: 'new-chat', label: 'New chat', icon: MessageSquarePlus, keywords: 'ask conversation start', run: () => go('/chat') };
  const listed: (PaletteAction & { flag?: FlagName })[] = [
    ...(pathname.startsWith('/chat') ? [newChat] : []),
    {
      id: 'copy-mcp-url',
      label: 'Copy MCP URL',
      flag: 'mcp_gateway',
      icon: Link2,
      keywords: 'connect assistant claude cursor copilot chatgpt mcp url',
      run: async () => {
        setOpen(false);
        try {
          const url = await connectUrl();
          await navigator.clipboard.writeText(url);
          toast.success('Copied the MCP URL', { description: url });
        } catch (e) {
          toast.error('Couldn’t copy the MCP URL', { description: (e as Error).message });
        }
      },
    },
    { id: 'new-workflow', label: 'New workflow', icon: Route, keywords: 'create add', run: () => go('/workflows?create=1') },
    { id: 'new-agent', label: 'New agent', icon: Bot, keywords: 'create add', run: () => go('/agents?create=1') },
    { id: 'generate-skill', label: 'Generate skill', icon: Sparkles, keywords: 'create add skill procedure sop draft ai', run: () => go('/skills?create=generate') },
    { id: 'new-skill', label: 'New skill', icon: Sparkles, keywords: 'create add blank skill procedure', run: () => go('/skills?create=1') },
    { id: 'connect-system', label: 'Connect a system', icon: Cable, keywords: 'integration connection oauth sharepoint servicenow salesforce credential', run: () => go('/integrations?tab=catalog') },
    { id: 'connect-mailbox', label: 'Connect mailbox', icon: Mail, keywords: 'email inbox deployment outlook', run: () => go('/channels/email/connect') },
    ...(pathname.startsWith('/chat') ? [] : [newChat]),
    { id: 'switch-team', label: 'Switch team', icon: Users, keywords: 'team change', opens: 'teams' },
  ];
  const actions: PaletteAction[] = useFlagged(listed);

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
