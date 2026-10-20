'use client';

import { SettingsSection } from '@/components/shared/settings-section';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import type { MemorySettings } from '@/lib/types/domain';

import type { AgentDraft } from './agent-settings';

const KINDS: { kind: MemorySettings['kinds'][number]; label: string; hint: string }[] = [
  { kind: 'fact', label: 'Facts', hint: 'About the person, like their timezone or preferred account.' },
  { kind: 'preference', label: 'Preferences', hint: 'How they like to be helped, like short answers.' },
  { kind: 'episode', label: 'Earlier chats', hint: 'One line on what they asked for each time.' },
];

/**
 * What the agent remembers about each person between chats (c-124, c-206), saved with the version like every other
 * setting. People see, correct and forget what it keeps from the chat; the workspace retention policy deletes old ones.
 */
export function MemorySection({ draft, set }: { draft: AgentDraft; set: (k: 'memory', v: MemorySettings) => void }) {
  const m = draft.memory;
  const toggle = (kind: MemorySettings['kinds'][number], on: boolean) =>
    set('memory', { ...m, kinds: on ? KINDS.map((k) => k.kind).filter((k) => k === kind || m.kinds.includes(k)) : m.kinds.filter((k) => k !== kind) });
  return (
    <SettingsSection title="Memory" description="What the agent keeps about each person it talks to, for their next chat with it. Only from what the person says, never from tool results.">
      <div className="flex flex-col gap-4" data-testid="agent-memory">
        <div className="flex items-center justify-between gap-4 rounded-md border bg-card px-3 py-2.5">
          <div>
            <Label htmlFor="memory-enabled">Remember people between chats</Label>
            <p className="text-xs text-muted-foreground">Each person sees what it keeps about them, and can correct or forget it.</p>
          </div>
          <Switch id="memory-enabled" checked={m.enabled} onCheckedChange={(v) => set('memory', { ...m, enabled: v })} />
        </div>
        {m.enabled && (
          <fieldset className="flex flex-col gap-3">
            <legend className="mb-2 text-sm font-medium">What it remembers</legend>
            {KINDS.map(({ kind, label, hint }) => (
              <div key={kind} className="flex items-start gap-2">
                <Checkbox id={`memory-kind-${kind}`} checked={m.kinds.includes(kind)} onCheckedChange={(v) => toggle(kind, v === true)} className="mt-0.5" />
                <div>
                  <Label htmlFor={`memory-kind-${kind}`}>{label}</Label>
                  <p className="text-xs text-muted-foreground">{hint}</p>
                </div>
              </div>
            ))}
          </fieldset>
        )}
      </div>
    </SettingsSection>
  );
}
