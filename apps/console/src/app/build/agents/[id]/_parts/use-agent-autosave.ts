'use client';

import * as React from 'react';
import { type AgentDraft, sameValue } from '@/components/agents/agent-settings';
import { useWorkspaceIdentity } from '@/hooks/me-queries';
import { useReadAgentAgain, type useUpdateAgent } from '@/hooks/queries';
import { useAutosave } from '@/hooks/use-autosave';
import { onStaleSave, staleSave } from '@/lib/save-base';
import type { Agent, AgentBrief, AgentPatch, PromptMode } from '@/lib/types/domain';

/** The fields of `draft` that differ from the saved agent, as one save sends them. */
export function agentPatch(saved: AgentDraft, draft: AgentDraft, brief: AgentBrief | null, mode: PromptMode): AgentPatch {
  const patch: Record<string, unknown> = Object.fromEntries(Object.entries(draft).filter(([k, v]) => !sameValue(saved[k as keyof AgentDraft], v)));
  // Sent only once the builder has edited a brief field: opening a legacy agent or saving a model change never converts it.
  if (brief) patch.brief = brief;
  if (mode === 'brief') (delete patch.instructions, delete patch.role);
  // The API pins by id and version; the name and tools a pin carries are what the API returned for display.
  // A new pin carries version 0 until saved; the service then pins the published version.
  if (patch.widgetPins) patch.widgetPins = draft.widgetPins.map((p) => ({ widgetId: p.widgetId, version: p.version || undefined }));
  return patch as AgentPatch;
}

/**
 * The agent's draft saves itself through `useAutosave`; this supplies what is particular to an agent. Each save names
 * the copy of the agent the page holds. One refused because that copy is old is handled by `refusal`:
 *
 * - after the person's own write (an @ insert, a grant, a skill attached), the newest copy is read and the change is
 *   sent once more, with no message. The page keeps every field the person changed and takes the rest.
 * - after another person's save, `stale` says who saved and when, and nothing is sent until `reload`, which reads
 *   their copy. The page then moves onto it, keeping only the fields this person changed (the brief field by field),
 *   and saves those on top.
 */
export function useAgentAutosave({
  agent,
  update,
  draft,
  saved,
  brief,
  mode,
  ready,
  onBriefSaved,
}: {
  agent: Agent;
  update: ReturnType<typeof useUpdateAgent>;
  draft: AgentDraft;
  saved: AgentDraft;
  /** The brief as edited, or null while the builder has not changed it. */
  brief: AgentBrief | null;
  mode: PromptMode;
  /** The page may save: the person may edit, something changed and every field is valid. */
  ready: boolean;
  onBriefSaved: (sent: AgentBrief) => void;
}) {
  const readAgain = useReadAgentAgain();
  const me = useWorkspaceIdentity()?.user.email;
  const patch = agentPatch(saved, draft, brief, mode);
  const auto = useAutosave({
    waiting: ready ? JSON.stringify([draft, brief]) : null,
    enabled: ready,
    settledOn: saved,
    readNewest: readAgain,
    send: () => update.mutateAsync({ ...patch, base: agent }),
    // The saved brief is the service's reading of what was sent; edits made while it was in flight stay.
    onSaved: () => patch.brief && onBriefSaved(patch.brief),
    refusal: (e) => {
      const refused = staleSave(e);
      const next = refused && onStaleSave(refused, me, agent.version);
      return next ? (next.resend ? { resend: true } : { stale: next.note }) : null;
    },
  });
  const reload = () => readAgain().then(() => auto.clearStale());
  return { saveNow: auto.saveNow, saveError: auto.error, stale: auto.stale, reload, reading: auto.reading, status: auto.status };
}
