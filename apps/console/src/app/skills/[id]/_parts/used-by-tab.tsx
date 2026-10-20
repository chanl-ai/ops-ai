'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowUpCircle, Bot } from 'lucide-react';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { DisabledReason } from '@/components/shared/disabled-reason';
import { EmptyState } from '@/components/shared/empty-state';
import { AgentAvailabilityBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useMoveSkillPin } from '@/hooks/skill-queries';
import { pct, relativeTime } from '@/lib/format';
import type { SkillDetail, SkillUsage } from '@/lib/types/skills';
import { TeamName } from '@/components/shared/team-name';

/** Agents that pin a version, how often it loads for each, and the upgrade to the latest published version. */
export function UsedByTab({ skill: s }: { skill: SkillDetail }) {
  const move = useMoveSkillPin();
  const [target, setTarget] = React.useState<SkillUsage | null>(null);

  if (!s.usage.length)
    return (
      <EmptyState
        icon={Bot}
        title="No agent uses this skill"
        description={s.publishedVersion ? 'Attach it from an agent’s page, in the Skills section. The agent must hold every tool and knowledge base it names.' : 'Publish a version first. Agents can only pin published versions.'}
        action={{ label: 'Open agents', href: '/agents' }}
      />
    );

  return (
    <div className="flex flex-col gap-3" data-testid="skill-used-by-tab">
      <p className="text-sm text-muted-foreground">Each agent keeps the version it pins until someone moves it. Moving a pin saves a new agent version; workflows adopt it on their next publish.</p>
      <div className="overflow-x-auto rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Agent</TableHead>
              <TableHead>Pinned</TableHead>
              <TableHead>Loads · 7 days</TableHead>
              <TableHead>Share of turns</TableHead>
              <TableHead>Last loaded</TableHead>
              <TableHead className="w-44" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {s.usage.map((u) => (
              <TableRow key={u.agentId} data-testid="skill-usage-row">
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Link href={`/agents/${u.agentId}`} className="font-medium underline-offset-2 hover:underline">
                      {u.agentName}
                    </Link>
                    <AgentAvailabilityBadge availability={u.agentAvailability} />
                  </div>
                  <div className="text-xs text-muted-foreground">
                    <TeamName teamId={u.agentTeamId} /> · attached {relativeTime(u.attachedAt)} by {u.attachedBy}
                  </div>
                </TableCell>
                <TableCell className="font-mono text-xs whitespace-nowrap">
                  v{u.pinnedVersion}
                  {u.latestPublished && u.latestPublished !== u.pinnedVersion && <span className="text-muted-foreground"> · latest v{u.latestPublished}</span>}
                </TableCell>
                <TableCell className="tabular-nums">{u.loads7d.toLocaleString('en-CA')}</TableCell>
                <TableCell className="tabular-nums">{pct(u.share7d)}</TableCell>
                <TableCell className="text-xs whitespace-nowrap text-muted-foreground">{u.lastLoadedAt ? relativeTime(u.lastLoadedAt) : 'Never'}</TableCell>
                <TableCell className="text-right">
                  {u.upgradeAvailable ? (
                    <DisabledReason reason={u.upgradeBlocked}>
                      <Button variant="outline" size="sm" disabled={!!u.upgradeBlocked} onClick={() => setTarget(u)} data-testid="move-pin-button">
                        <ArrowUpCircle className="size-3.5" /> Move to v{u.latestPublished}
                      </Button>
                    </DisabledReason>
                  ) : (
                    <span className="text-xs text-muted-foreground">{s.status === 'deprecated' ? 'Deprecated: replace it' : 'On the latest'}</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <DialogShell
        open={!!target}
        onOpenChange={(o) => !o && setTarget(null)}
        size="sm"
        title={`Move ${target?.agentName} to v${target?.latestPublished}?`}
        description={`Saves ${target?.agentName} as a new version with ${s.name} v${target?.latestPublished}. Workflows that use the agent adopt it on their next publish.`}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setTarget(null)} disabled={move.isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={move.isPending}
              onClick={async () => {
                if (!target?.latestPublished) return;
                try {
                  await move.mutateAsync({ agentId: target.agentId, skillId: s.id, version: target.latestPublished });
                  toast.success(`${target.agentName} now pins v${target.latestPublished}`, { description: 'Recorded in the agent’s versions and the audit log.' });
                  setTarget(null);
                } catch (e) {
                  toast.error('Couldn’t move the pin', { description: (e as Error).message });
                }
              }}
              data-testid="move-pin-confirm"
            >
              Move to v{target?.latestPublished}
            </LoadingButton>
          </div>
        }
      >
        <p className="text-sm text-muted-foreground">The agent must hold every tool and knowledge base the new version names.</p>
      </DialogShell>
    </div>
  );
}
