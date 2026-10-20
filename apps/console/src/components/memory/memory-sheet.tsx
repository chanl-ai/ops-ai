'use client';

import { DetailSheet } from '@/components/shared/detail-sheet';

import { MemoryList } from './memory-list';

/** The chat's What I remember: one agent's memories of the person, which they correct, forget and export (c-206). */
export function MemorySheet({ agentId, agentName, open, onOpenChange }: { agentId: string; agentName: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <DetailSheet open={open} onOpenChange={onOpenChange} title="What I remember" description={`What ${agentName} keeps about you from your chats.`} widthClass="sm:max-w-md" testId="memory-sheet">
      {open && <MemoryList agentId={agentId} />}
    </DetailSheet>
  );
}
