'use client';

import * as React from 'react';

import { DetailSheet } from '@/components/shared/detail-sheet';
import { Button } from '@/components/ui/button';
import { plural } from '@/lib/format';
import type { AgentUses } from '@/lib/types/domain';

/** "Uses 3 tools · 2 knowledge bases · 3 skills · 1 agent": the service's counts, with a kind left out when it is zero. */
export function usesLine(u: AgentUses | undefined): string {
  const parts = [
    u?.tools ? plural(u.tools, 'tool') : '',
    u?.knowledgeBases ? plural(u.knowledgeBases, 'knowledge base') : '',
    u?.skills ? plural(u.skills, 'skill') : '',
    u?.agents ? plural(u.agents, 'agent') : '',
    u?.workflows ? plural(u.workflows, 'workflow') : '',
  ].filter(Boolean);
  return parts.length ? `Uses ${parts.join(' · ')}` : 'Uses nothing yet';
}

/** The link under the brief that opens what the agent holds. */
export function AgentUsesLink({ uses, onOpen }: { uses: AgentUses | undefined; onOpen: () => void }) {
  return (
    <Button type="button" variant="link" className="h-auto self-start p-0 text-sm" onClick={onOpen} data-testid="agent-uses-link">
      {usesLine(uses)}
    </Button>
  );
}

/**
 * What the agent holds, in a sheet: its tools with accounts and approvals, its knowledge and its skills. The sections
 * are the ones the page showed before, handed in as children so they save with the same draft.
 */
export function AgentUsesSheet({ open, onOpenChange, uses, children }: { open: boolean; onOpenChange: (open: boolean) => void; uses: AgentUses | undefined; children: React.ReactNode }) {
  return (
    <DetailSheet open={open} onOpenChange={onOpenChange} title="What this agent uses" description={usesLine(uses)} widthClass="sm:max-w-3xl" testId="agent-uses-sheet">
      <div className="flex flex-col gap-4">{children}</div>
    </DetailSheet>
  );
}
