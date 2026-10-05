'use client';

import * as React from 'react';
import { AlertCircle, ChevronsUpDown, CreditCard, RotateCw, HandCoins, Layers, PiggyBank, Plus, ShieldAlert, Store, UserPlus, Users, type LucideIcon } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem, useSidebar } from '@/components/ui/sidebar';
import { plural } from '@/lib/format';
import type { Team, TeamIcon, TeamInput } from '@/lib/types/team';

export const TEAM_ICONS: Record<TeamIcon, LucideIcon> = {
  platform: Layers,
  lending: HandCoins,
  cards: CreditCard,
  fraud: ShieldAlert,
  onboarding: UserPlus,
  retail: Store,
  wealth: PiggyBank,
  team: Users,
};

/** Sidebar header: the current team, a menu to switch team (⌘1–⌘9) and to add one. Based on shadcn sidebar-07. */
export function TeamSwitcher({
  teams,
  activeTeam,
  subtitle,
  onSelect,
  ownerGroups,
  onCreate,
  isCreating,
  error,
  onRetry,
}: {
  /** The team list failed to load and there is nothing cached to show. */
  error?: boolean;
  onRetry?: () => void;
  teams: Team[];
  activeTeam: Team | undefined;
  /** Second line under the team name, e.g. "Northfield Bank · Ops AI". */
  subtitle: string;
  onSelect: (teamId: string) => void;
  /** Owner groups a new team can take responsibility for. */
  ownerGroups: string[];
  onCreate: (input: TeamInput) => Promise<unknown>;
  isCreating: boolean;
}) {
  const { isMobile } = useSidebar();
  const [adding, setAdding] = React.useState(false);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey) return;
      const n = Number(e.key);
      if (!Number.isInteger(n) || n < 1 || n > 9 || !teams[n - 1]) return;
      e.preventDefault();
      onSelect(teams[n - 1].id);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [teams, onSelect]);

  const Logo = TEAM_ICONS[activeTeam?.icon ?? 'platform'];

  if (error && !activeTeam)
    return (
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton size="lg" onClick={onRetry} aria-label="Teams unavailable. Try again">
            <div className="flex aspect-square size-8 items-center justify-center rounded-md bg-destructive/10 text-destructive">
              <AlertCircle className="size-4" />
            </div>
            <div className="grid flex-1 text-left leading-tight">
              <span className="truncate text-sm font-semibold">Teams unavailable</span>
              <span className="truncate text-xs text-muted-foreground">Try again</span>
            </div>
            <RotateCw className="ml-auto size-4 text-muted-foreground" />
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    );

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton size="lg" className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground" aria-label={`Team: ${activeTeam?.name ?? 'loading'}. Switch team`}>
              <div className="flex aspect-square size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
                <Logo className="size-4" />
              </div>
              <div className="grid flex-1 text-left leading-tight">
                <span className="truncate text-sm font-semibold">{activeTeam?.name ?? ' '}</span>
                <span className="truncate text-xs text-muted-foreground">{subtitle}</span>
              </div>
              <ChevronsUpDown className="ml-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-(--radix-dropdown-menu-trigger-width) min-w-60 rounded-lg" align="start" side={isMobile ? 'bottom' : 'right'} sideOffset={4}>
            <DropdownMenuLabel className="text-xs text-muted-foreground">Teams</DropdownMenuLabel>
            {teams.map((team, index) => {
              const Icon = TEAM_ICONS[team.icon];
              return (
                <DropdownMenuItem key={team.id} onClick={() => onSelect(team.id)} className="gap-2 p-2" aria-current={team.id === activeTeam?.id ? 'true' : undefined}>
                  <div className="flex size-6 items-center justify-center rounded-md border">
                    <Icon className="size-3.5 shrink-0" />
                  </div>
                  <div className="grid flex-1 leading-tight">
                    <span className={team.id === activeTeam?.id ? 'font-medium' : undefined}>{team.name}</span>
                    <span className="text-xs text-muted-foreground">{team.scope === 'all' ? 'All teams' : plural(team.memberCount, 'member')}</span>
                  </div>
                  {index < 9 && <DropdownMenuShortcut>⌘{index + 1}</DropdownMenuShortcut>}
                </DropdownMenuItem>
              );
            })}
            <DropdownMenuSeparator />
            <DropdownMenuItem className="gap-2 p-2" onSelect={() => setAdding(true)}>
              <div className="flex size-6 items-center justify-center rounded-md border bg-transparent">
                <Plus className="size-4" />
              </div>
              <div className="font-medium text-muted-foreground">Add team</div>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
      <AddTeamDialog open={adding} onOpenChange={setAdding} ownerGroups={ownerGroups} onSubmit={onCreate} isPending={isCreating} />
    </SidebarMenu>
  );
}

function AddTeamDialog({
  open,
  onOpenChange,
  ownerGroups,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ownerGroups: string[];
  onSubmit: (input: TeamInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const [values, setValues] = React.useState<TeamInput>({ name: '', ownerGroup: '' });
  const [errors, setErrors] = React.useState<{ name?: string; ownerGroup?: string }>({});
  const [submitError, setSubmitError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setValues({ name: '', ownerGroup: '' });
      setErrors({});
      setSubmitError(null);
    }
  }, [open]);

  const submit = async () => {
    const e = { name: values.name.trim() ? undefined : 'Name the team.', ownerGroup: values.ownerGroup ? undefined : 'Pick the owner group this team works on.' };
    setErrors(e);
    if (e.name || e.ownerGroup) return;
    try {
      await onSubmit({ ...values, name: values.name.trim() });
      onOpenChange(false);
    } catch (err) {
      setSubmitError((err as Error).message);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Add team"
      description="The team sees the agents, workflows, cases and knowledge its owner group is responsible for. You switch to it once it is created."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton onClick={submit} isLoading={isPending} loadingText="Adding…">
            Add team
          </LoadingButton>
        </div>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {submitError && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{submitError}</p>}
        <FormField id="team-name" label="Name" error={errors.name}>
          <Input id="team-name" value={values.name} onChange={(e) => (setValues((v) => ({ ...v, name: e.target.value })), setErrors((x) => ({ ...x, name: undefined })))} placeholder="e.g. Collections" aria-invalid={!!errors.name} />
        </FormField>
        <FormField id="team-owner" label="Owner group" error={errors.ownerGroup} hint="Records owned by this group appear for the team.">
          <Select value={values.ownerGroup} onValueChange={(g) => (setValues((v) => ({ ...v, ownerGroup: g })), setErrors((x) => ({ ...x, ownerGroup: undefined })))}>
            <SelectTrigger id="team-owner" className="w-full" aria-invalid={!!errors.ownerGroup}>
              <SelectValue placeholder="e.g. Lending Ops" />
            </SelectTrigger>
            <SelectContent>
              {ownerGroups.map((g) => (
                <SelectItem key={g} value={g}>
                  {g}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      </form>
    </DialogShell>
  );
}
