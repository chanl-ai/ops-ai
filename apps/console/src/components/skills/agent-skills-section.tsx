'use client';

import * as React from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { AlertTriangle, ArrowUpCircle, Plus, Sparkles, X } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { DisabledReason } from '@/components/shared/disabled-reason';
import { EntityPicker } from '@/components/shared/entity-picker';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Row, Rows } from '@/components/shared/surface';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { skillOptionsFor } from '@/hooks/options-queries';
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
  /** `version` omitted attaches the latest published one (the picker's choice). */
  onAttach: (skillId: string, version: number | undefined, name: string, moving: boolean) => Promise<unknown>;
  onDetach: (pin: AgentSkillPin) => Promise<unknown>;
  /** The attach dialog's state, owned by the page so other sections can open it with a filter; null when closed. */
  attach: AttachFilter | null;
  onAttachChange: (next: AttachFilter | null) => void;
}) {
  const [detaching, setDetaching] = React.useState<AgentSkillPin | null>(null);
  // The picker lists skills the agent can attach, searched on the server (c-136); the instructions toolbar opens it on always-on.
  const source = skillOptionsFor(data?.agentId ?? '', attach === 'always' ? 'always' : undefined);
  const attachSkill = async (ids: string[]) => {
    const id = ids[0];
    if (!id) return;
    onAttachChange(null);
    try {
      await onAttach(id, undefined, id, false);
    } catch (e) {
      toast.error('Couldn’t attach the skill', { description: (e as Error).message });
    }
  };
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
            <EntityPicker
              source={source}
              value={[]}
              onChange={attachSkill}
              multiple={false}
              addLabel={attach === 'always' ? 'Attach always-on skill' : 'Attach skill'}
              searchPlaceholder="Search skills…"
              emptyText="No published skill to attach. Skills from other teams cannot be attached yet."
              disabled={!!blockedReason || full || isPending || isError}
              open={attach !== null}
              onOpenChange={(o) => onAttachChange(o ? (attach ?? 'all') : null)}
              testId="attach-skill-button"
            />
          </DisabledReason>
        </CardAction>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <Skeleton className="h-20 w-full" />
        ) : isError || !data ? (
          <QueryError what="this agent’s skills" onRetry={onRetry} />
        ) : data.pins.length ? (
          <Rows className="rounded-md border" testId="agent-skill-pins">
            {data.pins.map((p) => (
              <Row
                key={p.skillId}
                wrap
                title={
                  <span className="flex flex-wrap items-center gap-2">
                    <Link href={`/skills/${p.skillId}`} className="underline-offset-2 hover:underline">
                      {p.name}
                    </Link>
                    <span className="font-mono text-xs font-normal text-muted-foreground">v{p.pinnedVersion}</span>
                    <AlwaysChip loading={p.loading} />
                    {p.status === 'deprecated' && (
                      <span className="inline-flex items-center gap-1 text-xs font-normal text-warning-text">
                        <AlertTriangle className="size-3" /> Deprecated: replace or detach it
                      </span>
                    )}
                  </span>
                }
                description={<span title={p.useWhen}>{p.loading === 'always' ? 'Added to every turn, after the agent’s instructions' : p.useWhen}</span>}
                trailing={
                  <>
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
                  </>
                }
              />
            ))}
          </Rows>
        ) : (
          <p className="rounded-md border border-dashed px-3 py-4 text-center text-sm text-muted-foreground">No skills attached. Attach a published skill from your team, or generate one on the Skills page.</p>
        )}
      </CardContent>

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
