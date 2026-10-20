'use client';

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle, Bot, PauseCircle, RotateCcw, SquareTerminal } from 'lucide-react';
import { toast } from 'sonner';

import { AssistantsPanel } from '@/components/deployments/mcp/assistants-panel';
import { CallsPanel } from '@/components/deployments/mcp/calls-panel';
import { EndpointPanel } from '@/components/deployments/mcp/endpoint-panel';
import { ConnectedStrip, JourneyBand } from '@/components/deployments/mcp/journey-band';
import { ToolsPanel } from '@/components/deployments/mcp/tools-panel';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { SettingsSection } from '@/components/shared/settings-section';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useConnect, useRecordCopy, useSaveConnectSettings, useSetExposed } from '@/hooks/connect-queries';
import { count, relativeTime } from '@/lib/format';
import type { ConnectAudience, ConnectRange, ConnectSettingsInput, ConnectTool } from '@/lib/types/connect';

const RANGE_LABEL: Record<ConnectRange, string> = { '24h': 'Last 24 hours', '7d': 'Last 7 days', '30d': 'Last 30 days' };
const LIFETIMES = [1, 8, 24, 168];
const lifetimeLabel = (h: number) => (h === 1 ? '1 hour' : h < 24 ? `${h} hours` : h === 24 ? '1 day' : `${h / 24} days`);
const DISMISS_KEY = 'ops-ai:connect-band-dismissed';

/**
 * The MCP channel of Deployments: one URL per workspace that staff paste into their own assistant. It shows
 * numbers and links out to where each thing is managed; the Expose switch, which creates, resumes or pauses a
 * workflow's MCP deployment, and the settings form are the only edits. `focusTools` scrolls to the exposed
 * workflows table, where the wizard sends someone who chose MCP.
 */
export function McpTab({ focusTools }: { focusTools?: boolean }) {
  const [range, setRange] = React.useState<ConnectRange>('7d');
  const query = useConnect({ range });
  const setExposed = useSetExposed();
  const recordCopy = useRecordCopy();
  const save = useSaveConnectSettings();
  const [pendingId, setPendingId] = React.useState<string | null>(null);
  // Dismissal is a per-viewer convenience, so it lives in browser storage and the page works without it.
  const [dismissed, setDismissed] = React.useState<string | null>(null);
  React.useEffect(() => {
    try {
      setDismissed(localStorage.getItem(DISMISS_KEY));
    } catch {
      setDismissed(null);
    }
  }, []);
  const dismiss = (which: 'band' | 'strip') => {
    setDismissed(which);
    try {
      localStorage.setItem(DISMISS_KEY, which);
    } catch {
      // Storage blocked: the band hides for this visit only.
    }
  };

  const o = query.data;
  const [draft, setDraft] = React.useState<ConnectSettingsInput | null>(null);
  const saved: ConnectSettingsInput | null = o ? { allowedTeams: o.settings.allowedTeams, defaultExposed: o.settings.defaultExposed, tokenLifetimeHours: o.settings.tokenLifetimeHours } : null;
  const form = draft ?? saved;
  const dirty = !!draft && !!saved && JSON.stringify(draft) !== JSON.stringify(saved);
  const set = (patch: Partial<ConnectSettingsInput>) => form && setDraft({ ...form, ...patch });

  const toggle = (t: ConnectTool, audience: ConnectAudience, exposed: boolean) => {
    setPendingId(t.workflowId);
    const done =
      audience === 'agents'
        ? exposed
          ? { title: `${t.name} is a tool for agents`, description: 'Grant it on an agent under Tools. Calling it starts a run of the newest published version, with its review gates.' }
          : { title: `Agents can no longer call ${t.name}`, description: 'The workflow tool is removed. No agent held a grant on it.' }
        : exposed
          ? { title: `Exposed ${t.name} to assistants`, description: 'Assistants see it as a tool on their next request. It runs the newest published version.' }
          : { title: `Stopped exposing ${t.name} to assistants`, description: 'Its MCP deployment is paused. Assistants no longer see the tool.' };
    setExposed.mutate(
      { workflowId: t.workflowId, audience, exposed },
      {
        onSuccess: () => toast.success(done.title, { description: done.description }),
        onError: (e) => toast.error(`Couldn’t change ${t.name}`, { description: e.message }),
        onSettled: () => setPendingId(null),
      },
    );
  };

  const submit = () =>
    draft &&
    save.mutate(draft, {
      onSuccess: () => {
        setDraft(null);
        toast.success('Saved connection settings');
      },
      onError: (e) => toast.error('Couldn’t save the settings', { description: e.message }),
    });

  const incomplete = o && !(o.journey.copiedUrl && o.journey.installedClient && o.journey.firstCall);
  const loaded = !!o;
  React.useEffect(() => {
    if (!focusTools || !loaded) return;
    // After the wizard's close, which hands focus back to the button that opened it.
    const t = setTimeout(() => {
      const el = document.querySelector<HTMLElement>('[data-testid=connect-tools]');
      el?.scrollIntoView({ block: 'start' });
      el?.querySelector<HTMLElement>('[role=switch]:not([disabled])')?.focus({ preventScroll: true });
    }, 350);
    return () => clearTimeout(t);
  }, [focusTools, loaded]);

  return (
    <>
      {query.isPending ? (
        <PageSkeleton statCards={4} tableRows={5} />
      ) : query.isError && !o ? (
        <QueryError what="the connection details" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
      ) : o && form ? (
        <div className="flex flex-col gap-4">
          {incomplete ? dismissed !== 'band' && <JourneyBand journey={o.journey} onDismiss={() => dismiss('band')} /> : dismissed !== 'strip' && <ConnectedStrip assistants={o.assistantCount} onDismiss={() => dismiss('strip')} />}

          <EndpointPanel url={o.url} authLabel={o.authLabel} exposedCount={o.exposedCount} live={o.live} onCopied={() => !o.journey.copiedUrl && recordCopy.mutate()} />

          <div className="flex justify-end">
            <ToggleGroup type="single" variant="outline" size="sm" value={range} onValueChange={(v) => v && setRange(v as ConnectRange)} aria-label="Range" data-testid="connect-range">
              <ToggleGroupItem value="24h">24 hours</ToggleGroupItem>
              <ToggleGroupItem value="7d">7 days</ToggleGroupItem>
              <ToggleGroupItem value="30d">30 days</ToggleGroupItem>
            </ToggleGroup>
          </div>
          <StatCardGrid columns={4}>
            <StatCard label="Calls over MCP" value={count(o.stats.calls)} icon={SquareTerminal} footer={{ text: RANGE_LABEL[range], subtext: 'Across exposed workflows' }} />
            <StatCard label="Held for approval" value={count(o.stats.held)} icon={PauseCircle} footer={{ text: 'Waited for a person', subtext: 'Decided in Reviews' }} />
            <StatCard label="Failed" value={count(o.stats.failed)} icon={AlertTriangle} footer={{ text: 'Errors returned to the assistant', subtext: 'Details in Activity' }} />
            <StatCard label="Assistants" value={count(o.stats.assistants)} icon={Bot} footer={{ text: 'Distinct people and clients', subtext: RANGE_LABEL[range] }} />
          </StatCardGrid>
          <CallsPanel series={o.series} held={o.stats.held} failed={o.stats.failed} rangeLabel={RANGE_LABEL[range]} />

          <ToolsPanel tools={o.tools} workflowCount={o.workflowCount} exposedCount={o.exposedCount} pendingId={pendingId} onToggle={toggle} />
          <AssistantsPanel assistants={o.assistants} total={o.assistantCount} />

          <SettingsSection title="Connection settings" description={`Last changed by ${o.settings.updatedBy} ${relativeTime(o.settings.updatedAt)}`}>
            <div className="grid gap-6 md:grid-cols-3" data-testid="connect-settings">
              <fieldset className="flex flex-col gap-2">
                <legend className="mb-1 text-sm font-medium">Who may connect</legend>
                <p className="text-xs text-muted-foreground">{form.allowedTeams.length ? 'Only the teams ticked here.' : 'Every team. Tick teams to limit it.'}</p>
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                  {o.teams.map((t) => (
                    <label key={t} className="flex items-center gap-2 text-sm">
                      <Checkbox checked={form.allowedTeams.includes(t)} onCheckedChange={(v) => set({ allowedTeams: v === true ? [...form.allowedTeams, t] : form.allowedTeams.filter((x) => x !== t) })} />
                      {t}
                    </label>
                  ))}
                </div>
              </fieldset>
              <div className="flex flex-col gap-2">
                <Label htmlFor="connect-default">New workflows</Label>
                <div className="flex items-center gap-2">
                  <Switch id="connect-default" checked={form.defaultExposed} onCheckedChange={(v) => set({ defaultExposed: v })} />
                  <span className="text-sm">{form.defaultExposed ? 'Exposed when first published' : 'Not exposed until switched on'}</span>
                </div>
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="connect-lifetime">Sign-in lasts</Label>
                <Select value={String(form.tokenLifetimeHours)} onValueChange={(v) => set({ tokenLifetimeHours: Number(v) })}>
                  <SelectTrigger id="connect-lifetime" className="w-48">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LIFETIMES.map((h) => (
                      <SelectItem key={h} value={String(h)}>
                        {lifetimeLabel(h)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">After this, the assistant asks the person to sign in again.</p>
              </div>
            </div>
            <p className="mt-4 text-sm">
              <Link href="/deployments" className="text-muted-foreground underline underline-offset-2">
                Advanced: API deployments
              </Link>
            </p>
          </SettingsSection>

          {dirty && (
            <div data-unsaved-bar className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-background/95 px-4 py-3 shadow-sm backdrop-blur">
              <span className="text-sm text-muted-foreground">Unsaved changes</span>
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => setDraft(null)} disabled={save.isPending}>
                  <RotateCcw className="size-3.5" /> Discard
                </Button>
                <LoadingButton size="sm" isLoading={save.isPending} onClick={submit}>
                  Save changes
                </LoadingButton>
              </div>
            </div>
          )}
        </div>
      ) : null}
    </>
  );
}
