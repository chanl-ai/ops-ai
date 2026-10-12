'use client';

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle, ArrowUpCircle, Plus, Sparkles, X } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { DisabledReason } from '@/components/shared/disabled-reason';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { pct, plural } from '@/lib/format';
import type { AgentSkillPin, AgentSkills, SkillLoading } from '@/lib/types/skills';
import { cn } from '@/lib/utils';

import { AlwaysChip } from './skill-loading';

/** Which skills the attach dialog lists; the instructions toolbar opens it on `always`. */
export type AttachFilter = 'all' | SkillLoading;

/**
 * The agent's skills: each pinned version, how often it loads, upgrade prompts, attach and detach. Attaching,
 * detaching or moving a pin saves a new agent version, so it is offered only when the settings form has no
 * unsaved changes.
 */
export function AgentSkillsSection({
  agentName,
  data,
  isPending,
  isError,
  onRetry,
  blockedReason,
  busy,
  onAttach,
  onDetach,
  attach,
  onAttachChange,
}: {
  agentName: string;
  data?: AgentSkills;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  /** Why pins cannot change right now, e.g. unsaved settings. */
  blockedReason?: string;
  busy: boolean;
  onAttach: (skillId: string, version: number, name: string, moving: boolean) => Promise<unknown>;
  onDetach: (pin: AgentSkillPin) => Promise<unknown>;
  /** The attach dialog's state, owned by the page so other sections can open it with a filter; null when closed. */
  attach: AttachFilter | null;
  onAttachChange: (next: AttachFilter | null) => void;
}) {
  const attachOpen = attach !== null;
  const setAttachOpen = (open: boolean) => onAttachChange(open ? 'all' : null);
  const filter = attach ?? 'all';
  const [chosen, setChosen] = React.useState<string | null>(null);
  const [detaching, setDetaching] = React.useState<AgentSkillPin | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (attachOpen) {
      setChosen(null);
      setError(null);
    }
  }, [attachOpen]);
  const shown = (data?.available ?? []).filter((a) => filter === 'all' || a.loading === filter);
  const pick = shown.find((a) => a.skillId === chosen);
  const full = !!data && data.pins.length >= data.limits.maxAttached;

  return (
    <Card data-testid="agent-skills-section">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base font-medium">
          <Sparkles className="size-4 text-muted-foreground" /> Skills
        </CardTitle>
        <CardDescription>
          Procedures {agentName} loads when a message matches their use-when line, at most {data?.limits.maxPerTurn ?? 2} a turn, and always-on skills that add to every turn. Each pins a published version.
        </CardDescription>
        <CardAction>
          <DisabledReason reason={blockedReason ?? (full ? `${agentName} already has ${data?.limits.maxAttached} skills.` : undefined)}>
            <Button variant="outline" size="sm" onClick={() => onAttachChange('all')} disabled={!!blockedReason || full || isPending || isError} data-testid="attach-skill-button">
              <Plus className="size-3.5" /> Attach skill
            </Button>
          </DisabledReason>
        </CardAction>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <Skeleton className="h-20 w-full" />
        ) : isError || !data ? (
          <QueryError what="this agent’s skills" onRetry={onRetry} />
        ) : data.pins.length ? (
          <ul className="divide-y rounded-md border" data-testid="agent-skill-pins">
            {data.pins.map((p) => (
              <li key={p.skillId} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <Link href={`/skills/${p.skillId}`} className="font-medium underline-offset-2 hover:underline">
                      {p.name}
                    </Link>
                    <span className="font-mono text-xs text-muted-foreground">v{p.pinnedVersion}</span>
                    <AlwaysChip loading={p.loading} />
                    {p.status === 'deprecated' && (
                      <span className="inline-flex items-center gap-1 text-xs text-warning-text">
                        <AlertTriangle className="size-3" /> Deprecated: replace or detach it
                      </span>
                    )}
                  </div>
                  <p className="truncate text-xs text-muted-foreground" title={p.useWhen}>
                    {p.loading === 'always' ? 'Added to every turn, after the agent’s instructions' : p.useWhen}
                  </p>
                </div>
                <div className="w-36 text-right text-xs">
                  <div className="tabular-nums">{plural(p.loads7d, 'load')} · 7 days</div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted" aria-label={`${pct(p.share7d)} of turns`}>
                    <div className="h-full rounded-full bg-primary/70" style={{ width: `${Math.min(100, Math.max(2, p.share7d * 300))}%` }} />
                  </div>
                  <div className="mt-0.5 text-muted-foreground tabular-nums">{pct(p.share7d)} of turns</div>
                </div>
                {p.upgradeAvailable && (
                  <DisabledReason reason={blockedReason ?? p.upgradeBlocked}>
                    <Button variant="outline" size="sm" disabled={!!blockedReason || !!p.upgradeBlocked || busy} onClick={() => onAttach(p.skillId, p.latestPublished!, p.name, true)} data-testid="agent-skill-upgrade">
                      <ArrowUpCircle className="size-3.5" /> Move to v{p.latestPublished}
                    </Button>
                  </DisabledReason>
                )}
                <DisabledReason reason={blockedReason}>
                  <Button variant="ghost" size="icon" className="size-7" disabled={!!blockedReason || busy} aria-label={`Detach ${p.name}`} onClick={() => setDetaching(p)}>
                    <X className="size-3.5" />
                  </Button>
                </DisabledReason>
              </li>
            ))}
          </ul>
        ) : (
          <p className="rounded-md border border-dashed px-3 py-4 text-center text-sm text-muted-foreground">No skills attached. Attach a published skill from your team, or generate one on the Skills page.</p>
        )}
      </CardContent>

      <DialogShell
        open={attachOpen}
        onOpenChange={setAttachOpen}
        size="md"
        title={filter === 'always' ? `Attach an always-on skill to ${agentName}` : `Attach a skill to ${agentName}`}
        description="Published skills from the agent’s team. A skill only works with tools and knowledge the agent already holds."
        footer={
          <div className="flex w-full items-center justify-end gap-2">
            <span className="mr-auto text-xs text-destructive">{error}</span>
            <Button variant="outline" onClick={() => setAttachOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={busy}
              disabled={!pick?.attachable}
              onClick={async () => {
                if (!pick) return;
                try {
                  await onAttach(pick.skillId, pick.latestPublished, pick.name, false);
                  setAttachOpen(false);
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
              data-testid="attach-skill-submit"
            >
              {pick ? `Attach v${pick.latestPublished}` : 'Attach'}
            </LoadingButton>
          </div>
        }
      >
        <Tabs value={filter} onValueChange={(v) => (setChosen(null), onAttachChange(v as AttachFilter))} className="mb-3">
          <TabsList aria-label="Loading">
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="always">Always on</TabsTrigger>
            <TabsTrigger value="on_match">On match</TabsTrigger>
          </TabsList>
        </Tabs>
        {shown.length ? (
          <div className="flex flex-col gap-2" role="radiogroup" aria-label="Skills" data-testid="attach-skill-options">
            {shown.map((a) => (
              <button
                key={a.skillId}
                type="button"
                role="radio"
                aria-checked={chosen === a.skillId}
                disabled={!a.attachable}
                onClick={() => setChosen(a.skillId)}
                className={cn('flex flex-col gap-0.5 rounded-lg border p-3 text-left hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60', chosen === a.skillId && 'border-primary bg-primary/5')}
              >
                <span className="flex items-center gap-2 text-sm font-medium">
                  {a.name} <span className="font-mono text-xs font-normal text-muted-foreground">v{a.latestPublished}</span>
                  <AlwaysChip loading={a.loading} />
                </span>
                <span className="text-xs text-muted-foreground">{a.loading === 'always' ? 'Added to every turn, after the agent’s instructions' : a.useWhen}</span>
                {!a.attachable && <span className="text-xs text-destructive">Needs {a.missing.join(', ')}. Grant them on this agent first.</span>}
              </button>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {filter === 'always' ? 'No always-on skill left to attach. Shared wording such as disclosures and tone guides is published as an always-on skill on the Skills page.' : 'No published skills to attach. Skills from other teams cannot be attached yet.'}
          </p>
        )}
        <p className="mt-3 text-xs text-muted-foreground">Attaching saves {agentName} as a new version. Workflows that use it adopt the change on their next publish.</p>
      </DialogShell>
      <DialogShell
        open={!!detaching}
        onOpenChange={(o) => !o && setDetaching(null)}
        size="sm"
        title={`Detach ${detaching?.name}?`}
        description={`Saves ${agentName} as a new version without it. Requests it handled are answered from the agent’s own instructions.`}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setDetaching(null)} disabled={busy}>
              Cancel
            </Button>
            <LoadingButton
              variant="destructive"
              isLoading={busy}
              onClick={async () => {
                if (!detaching) return;
                await onDetach(detaching);
                setDetaching(null);
              }}
              data-testid="detach-skill-confirm"
            >
              Detach
            </LoadingButton>
          </div>
        }
      >
        <p className="text-sm text-muted-foreground">It loaded in {plural(detaching?.loads7d ?? 0, 'turn')} in the last 7 days.</p>
      </DialogShell>
    </Card>
  );
}
