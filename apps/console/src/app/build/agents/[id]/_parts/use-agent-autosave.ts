'use client';

import * as React from 'react';
import { type AgentDraft, sameValue } from '@/components/agents/agent-settings';
import { useWorkspaceIdentity } from '@/hooks/me-queries';
import { useReadAgentAgain, type useUpdateAgent } from '@/hooks/queries';
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
 * The one draft saves itself: a second after the last valid change, with no dialog and no note per save. Each save
 * names the copy of the agent the page holds. One refused because that copy is old is handled here:
 *
 * - after the person's own write (an @ insert, a grant, a skill attached), the newest copy is read and the change is
 *   sent once more, with no message. The page keeps every field the person changed and takes the rest.
 * - after another person's save, `stale` says who saved and when, and nothing is sent until `reload`. The person's
 *   unsaved text stays on the page through the reload and saves on top of the copy they then see.
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
  const [saveError, setSaveError] = React.useState<string | null>(null);
  // What a save failed on: autosave does not send it again until it changes or Retry is pressed.
  const [failed, setFailed] = React.useState<string | null>(null);
  const [stale, setStale] = React.useState<string | null>(null);
  // The newest copy is being read after a refused save; the next save waits for it, or it would name the old copy again.
  const [reading, setReading] = React.useState(false);
  // What was last sent again after the person's own write, so one change is sent again once.
  const resent = React.useRef<string | null>(null);
  const editing = JSON.stringify([draft, brief]);

  const read = () => {
    setReading(true);
    return readAgain().finally(() => setReading(false));
  };
  const saveNow = () => {
    const sent = editing;
    const patch = agentPatch(saved, draft, brief, mode);
    update.mutate(
      { ...patch, base: agent },
      {
        onSuccess: () => {
          // The saved brief is the service's reading of what was sent; edits made while it was in flight stay.
          if (patch.brief) onBriefSaved(patch.brief);
          setSaveError(null);
          setFailed(null);
          resent.current = null;
        },
        onError: (e) => {
          const refused = staleSave(e);
          const next = refused && onStaleSave(refused, me);
          if (next?.resend && resent.current !== sent) {
            resent.current = sent;
            return void read();
          }
          if (next && !next.resend) return setStale(next.note);
          setSaveError(e.message);
          setFailed(sent);
        },
      },
    );
  };
  React.useEffect(() => {
    if (!ready || update.isPending || reading || stale || failed === editing) return;
    const t = setTimeout(() => saveNow(), 1000);
    return () => clearTimeout(t);
    // Saves on a change to the draft or once the last save has settled; the patch reads `saved`, which moves with them.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, saved, ready, update.isPending, reading, stale, failed]);

  const reload = () => read().then(() => setStale(null));
  return { saveNow, saveError, stale, reload, reading };
}
