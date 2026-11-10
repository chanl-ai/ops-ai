'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { Check, Circle, CircleDot, Plug } from 'lucide-react';
import { toast } from 'sonner';

import { AppLogo } from '@/components/shared/app-logo';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useChatConnectors, useNewChatConnectors, useSetChatConnectors } from '@/hooks/chat-settings-queries';
import type { ChatConnector } from '@/lib/types/chat';
import { cn } from '@/lib/utils';
import { APP_STATES, appStateFor, labelFor } from '@/lib/app-state';
import { appPageHref } from '@/lib/app-links';
import { useCan } from '@/hooks/me-queries';

/** Where a connector's one action is taken: the person's own sign-in on Connectors (Mine), an admin's on Team setup. */
const MINE = '/integrations/my-accounts';

/**
 * The composer's connector picker: every connector the chat may use, the ones it uses checked (every connected one in a
 * new chat), then those that need the person's sign-in and those off for the team, each with its one action. Unchecking
 * one leaves its tools out of this chat only; the list holds only what the team gave this agent, so it never adds one.
 */
function ConnectorsMenu({
  open,
  setOpen,
  rows,
  pending,
  failed,
  saving,
  onToggle,
  onPick,
  disabled,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
  rows: ChatConnector[];
  pending: boolean;
  failed: boolean;
  saving: boolean;
  onToggle: (c: ChatConnector) => void;
  /** Picks the account this chat uses for an app; absent before the chat exists, where the default is used. */
  onPick?: (c: ChatConnector, account: string) => void;
  disabled?: boolean;
}) {
  // The app whose accounts are open under it, after Change.
  const [changing, setChanging] = React.useState<string | null>(null);
  const router = useRouter();
  const go = (href: string) => (setOpen(false), router.push(href));
  // Whoever manages the team's apps is offered the team's step; anyone else asks them (lib/app-state.ts).
  const manages = useCan('connections', 'manage') === true;
  // Grouped by who acts next, as tools-service answers it (appGroup); the words come from lib/app-state.ts.
  const usable = rows.filter((c) => c.appGroup === 'on');
  const signIn = rows.filter((c) => c.appGroup === 'needs_you');
  const off = rows.filter((c) => c.appGroup === 'needs_admin');
  const inUse = usable.filter((c) => c.on);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 gap-1.5 px-2 text-xs"
          disabled={disabled}
          aria-label={inUse.length ? `Connectors for this chat: ${inUse.map((c) => c.name).join(', ')}` : 'Connectors for this chat'}
          data-testid="connectors-picker"
        >
          <Plug className="size-4" />
          <span className="max-sm:sr-only">Connectors</span>
          {inUse.length > 0 && (
            <span className="flex items-center -space-x-1" data-testid="connectors-in-use">
              {inUse.slice(0, 4).map((c) => (
                <AppLogo key={c.appId} name={c.name} logo={c.logo} title={c.name} className="size-4 rounded-sm ring-1 ring-background" />
              ))}
              {inUse.length > 4 && <span className="pl-2 text-muted-foreground">+{inUse.length - 4}</span>}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      {/* React events bubble out of the portal to the composer, whose input group focuses the text box on click; that
          closed the list mid-click and dropped the click on whatever lay under it, so clicks stop at the list. */}
      <PopoverContent align="start" className="w-80 max-w-[calc(100vw-2rem)] p-0" data-testid="connectors-picker-list" onClick={(e) => e.stopPropagation()}>
        <Command>
          <CommandInput placeholder="e.g. Salesforce" />
          <CommandList className="max-h-80">
            {pending ? (
              <p className="px-3 py-4 text-sm text-muted-foreground">Loading connectors…</p>
            ) : failed ? (
              <p className="px-3 py-4 text-sm text-destructive-text">Couldn’t load this chat’s connectors. Close and open again to retry.</p>
            ) : (
              <>
                <CommandEmpty>{rows.length ? 'No connector matches.' : 'This agent uses no connector.'}</CommandEmpty>
                {usable.length > 0 && (
                  <CommandGroup heading="On in this chat">
                    {usable.map((c) => {
                      // The tick stays the app's on or off for this chat; the account in use is a line under it.
                      const several = (c.accounts ?? []).length > 1;
                      const inUse = c.account ?? (c.accounts ?? []).find((a) => a.default)?.name ?? null;
                      return (
                        <React.Fragment key={c.appId}>
                          <CommandItem value={c.name} onSelect={() => onToggle(c)} disabled={saving} data-testid={`connector-toggle-${c.appId}`} data-on={c.on} data-state={APP_STATES[c.appState].label}>
                            <AppLogo name={c.name} logo={c.logo} className="size-4 rounded-sm" />
                            <span className="flex-1 truncate">{c.name}</span>
                            <Check className={cn('size-4', c.on ? 'opacity-100' : 'opacity-0')} />
                          </CommandItem>
                          {several && c.on && (
                            <div className="flex items-center gap-1 pb-1.5 pl-8 pr-2 text-xs text-muted-foreground" data-testid={`connector-account-${c.appId}`}>
                              <span className="min-w-0 flex-1 truncate">{inUse ? `Uses ${inUse}` : 'Uses your default'}</span>
                              {onPick && (
                                <Button type="button" variant="link" size="sm" className="h-6 min-w-6 px-1 text-xs" onClick={() => setChanging(changing === c.appId ? null : c.appId)} data-testid={`connector-change-${c.appId}`}>
                                  Change
                                </Button>
                              )}
                            </div>
                          )}
                          {several && c.on && changing === c.appId &&
                            (c.accounts ?? []).map((a) => (
                              <CommandItem
                                key={`${c.appId}:${a.name}`}
                                value={`${c.name} ${a.name}`}
                                className="pl-8"
                                disabled={saving}
                                onSelect={() => (onPick?.(c, a.name), setChanging(null))}
                                data-testid={`connector-pick-${c.appId}-${a.name}`}
                              >
                                {a.name === inUse ? <CircleDot className="size-3.5" /> : <Circle className="size-3.5" />}
                                <span className="flex min-w-0 flex-1 flex-col">
                                  <span className="truncate">{a.name}</span>
                                  <span className="truncate text-xs text-muted-foreground">{a.identity.map((e) => e.shown).join(' · ')}</span>
                                </span>
                              </CommandItem>
                            ))}
                        </React.Fragment>
                      );
                    })}
                  </CommandGroup>
                )}
                {signIn.length > 0 && (
                  <CommandGroup heading="Needs your sign-in">
                    {signIn.map((c) => (
                      <CommandItem key={c.appId} value={c.name} data-testid={`connector-sign-in-${c.appId}`} data-state={APP_STATES[c.appState].label}>
                        <AppLogo name={c.name} logo={c.logo} className="size-4 rounded-sm opacity-60" />
                        <span className="flex-1 truncate text-muted-foreground">{c.name}</span>
                        {c.personal ? (
                          <Button type="button" variant="outline" size="sm" className="h-6 px-2 text-xs" onClick={() => go(MINE)}>
                            Connect
                          </Button>
                        ) : (
                          <span className="text-xs text-muted-foreground">an admin signs in</span>
                        )}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                )}
                {off.length > 0 && (
                  <CommandGroup heading="Off for this team">
                    {off.map((c) => (
                      <CommandItem key={c.appId} value={c.name} className="flex-wrap" data-testid={`connector-off-${c.appId}`} data-state={labelFor(c.appState, manages)}>
                        <AppLogo name={c.name} logo={c.logo} className="size-4 rounded-sm opacity-60" />
                        <span className="flex-1 truncate text-muted-foreground">{c.name}</span>
                        <OffAction c={c} manages={manages} go={go} />
                      </CommandItem>
                    ))}
                  </CommandGroup>
                )}
              </>
            )}
          </CommandList>
          <p className="border-t px-3 py-2 text-xs text-muted-foreground">Only tools the team gave this agent. Turning one off narrows this chat; it never adds tools.</p>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

/** An app the team acts on first, in the picker: the caller's one step from the state table, by role. */
function OffAction({ c, manages, go }: { c: ChatConnector; manages: boolean; go: (href: string) => void }) {
  const { action } = appStateFor(c.appState, c.appGroup, manages);
  const label = action === 'turn_on' ? 'Turn on' : action === 'add_auth_config' ? 'Set up' : action === 'fix_auth_config' ? 'Fix' : action === 'connect' || action === 'sign_in' ? 'Connect' : null;
  if (label)
    return (
      <Button type="button" variant="outline" size="sm" className="h-6 px-2 text-xs" onClick={() => go(appPageHref(c.appId))} data-testid={`connector-off-action-${c.appId}`}>
        {label}
      </Button>
    );
  // Below the name at every screen width: the list is a fixed w-80, and beside the name this line left it an initial.
  return <span className="basis-full pl-6 text-xs text-muted-foreground">{labelFor(c.appState, manages)} · ask an admin</span>;
}

/** The whole set an unchecked or checked connector makes: the apps left out, as the chat's PUT takes them. */
function nextOff(rows: ChatConnector[], c: ChatConnector): string[] {
  const left = rows.filter((r) => r.appGroup !== 'needs_admin' && !r.on).map((r) => r.appId);
  return c.on ? [...left, c.appId] : left.filter((id) => id !== c.appId);
}

/** The accounts this chat already chose, app id to name, which a new pick keeps beside its own. */
function chosen(rows: ChatConnector[]): Record<string, string> {
  return Object.fromEntries(rows.filter((r) => r.account).map((r) => [r.appId, r.account as string]));
}

/** The picker on a chat that exists: each change is saved on the chat at once. */
export function ConnectorsPicker({ threadId, disabled }: { threadId: string; disabled?: boolean }) {
  const [open, setOpen] = React.useState(false);
  const found = useChatConnectors(threadId);
  const save = useSetChatConnectors(threadId);
  const rows = found.data?.connectors ?? [];
  return (
    <ConnectorsMenu
      open={open}
      setOpen={setOpen}
      rows={rows}
      pending={found.isPending}
      failed={found.isError}
      saving={save.isPending}
      disabled={disabled}
      onToggle={(c) => save.mutate(nextOff(rows, c), { onError: (e) => toast.error(`Couldn’t change ${c.name} for this chat`, { description: e.message }) })}
      onPick={(c, account) =>
        save.mutate(
          { off: rows.filter((r) => r.appGroup !== 'needs_admin' && !r.on).map((r) => r.appId), accounts: { ...chosen(rows), [c.appId]: account } },
          { onError: (e) => toast.error(`Couldn’t change ${c.name}’s account for this chat`, { description: e.message }) },
        )
      }
    />
  );
}

/**
 * The picker on Chat's home, before the chat exists: the agent's connectors, every one on, and the choice kept here;
 * the chat takes it as soon as the first message makes it, before that message is sent.
 */
export function NewChatConnectorsPicker({ agentId, off, onChange, disabled }: { agentId?: string; off: string[]; onChange: (off: string[]) => void; disabled?: boolean }) {
  const [open, setOpen] = React.useState(false);
  const found = useNewChatConnectors(agentId);
  const rows = (found.data?.connectors ?? []).map((c) => (c.appGroup === 'needs_admin' ? c : { ...c, on: !off.includes(c.appId) }));
  return <ConnectorsMenu open={open} setOpen={setOpen} rows={rows} pending={found.isPending} failed={found.isError} saving={false} disabled={disabled} onToggle={(c) => onChange(nextOff(rows, c))} />;
}
