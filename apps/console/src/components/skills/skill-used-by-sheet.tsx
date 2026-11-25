'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowUpCircle, Bot } from 'lucide-react';
import { toast } from 'sonner';

import { DetailSheet } from '@/components/shared/detail-sheet';
import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { DisabledReason } from '@/components/shared/disabled-reason';
import { EmptyState } from '@/components/shared/empty-state';
import { Row, Rows } from '@/components/shared/surface';
import { AgentAvailabilityBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { useMoveSkillPin } from '@/hooks/skill-queries';
import { pct, plural, relativeTime } from '@/lib/format';
import type { SkillDetail, SkillUsage as SkillUsageRow } from '@/lib/types/skills';
import { TeamName } from '@/components/shared/team-name';

/**
 * The agents that pin a version of the skill, opened from the page's "Used by" link. `canEdit` false leaves out the
 * move to the latest version, for a person who may not change the team's agents.
 */
export function SkillUsedBySheet({ skill: s, open, onOpenChange, canEdit }: { skill: SkillDetail; open: boolean; onOpenChange: (open: boolean) => void; canEdit: boolean }) {
  return (
    <DetailSheet
      open={open}
      onOpenChange={onOpenChange}
      title={s.usedBy ? `Used by ${plural(s.usedBy, 'agent')}` : 'Used by no agent'}
      description="Each agent keeps the version it pins until someone moves it."
      testId="skill-used-by-sheet"
      footerActions={
        <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
          Close
        </Button>
      }
    >
      <SkillUsage skill={s} canEdit={canEdit} />
    </DetailSheet>
  );
}

/** Agents that pin a version, how often it loads for each, and the upgrade to the latest published version. */
function SkillUsage({ skill: s, canEdit }: { skill: SkillDetail; canEdit: boolean }) {
  const move = useMoveSkillPin();
  const [target, setTarget] = React.useState<SkillUsageRow | null>(null);

  if (!s.usage.length)
    return (
      <EmptyState
        icon={Bot}
        title="No agent uses this skill"
        description={s.publishedVersion ? 'Attach it from an agent’s page, in the Skills section. The agent must hold every tool and knowledge base it names.' : 'Publish a version first. Agents can only pin published versions.'}
        action={{ label: 'Open agents', href: '/build/agents' }}
      />
    );

  return (
    <div className="flex flex-col gap-3" data-testid="skill-used-by">
      <p className="text-sm text-muted-foreground">Moving a pin saves a new agent version; workflows adopt it on their next publish.</p>
      <Rows className="rounded-md border bg-card" testId="skill-usage-rows">
        {s.usage.map((u) => (
          <Row
            key={u.agentId}
            wrap
            title={
              <span className="flex flex-wrap items-center gap-2">
                <Link href={`/build/agents/${u.agentId}`} className="underline-offset-2 hover:underline">
                  {u.agentName}
                </Link>
                <AgentAvailabilityBadge availability={u.agentAvailability} />
              </span>
            }
            description={
              <>
                <TeamName teamId={u.agentTeamId} /> · attached {relativeTime(u.attachedAt)} by {u.attachedBy}
              </>
            }
            trailing={
              u.upgradeAvailable && !canEdit ? (
                <span className="text-xs text-muted-foreground">v{u.latestPublished} is available</span>
              ) : u.upgradeAvailable ? (
                <DisabledReason reason={u.upgradeBlocked}>
                  <Button variant="outline" size="sm" disabled={!!u.upgradeBlocked} onClick={() => setTarget(u)} data-testid="move-pin-button">
                    <ArrowUpCircle className="size-3.5" /> Update
                  </Button>
                </DisabledReason>
              ) : (
                <span className="text-xs text-muted-foreground">{s.status === 'deprecated' ? 'Deprecated: replace it' : 'On the latest'}</span>
              )
            }
          >
            <p className="text-xs tabular-nums">
              Uses v{u.pinnedVersion} · {u.loads7d.toLocaleString('en-CA')} loads in 7 days · {pct(u.share7d)} of its turns · {u.lastLoadedAt ? `last loaded ${relativeTime(u.lastLoadedAt)}` : 'never loaded'}
            </p>
          </Row>
        ))}
      </Rows>
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
              Update
            </LoadingButton>
          </div>
        }
      >
        <p className="text-sm text-muted-foreground">The agent must hold every tool and knowledge base the new version names.</p>
      </DialogShell>
    </div>
  );
}
