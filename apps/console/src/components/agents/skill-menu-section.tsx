'use client';

import { SettingsSection } from '@/components/shared/settings-section';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import type { SkillMenu } from '@/lib/types/domain';

import type { AgentDraft } from './agent-settings';

const CHOICES: { value: SkillMenu; label: string; hint: (attached: number) => string }[] = [
  { value: 'attached', label: 'Only attached skills', hint: (n) => `The / menu lists the ${n} skill${n === 1 ? '' : 's'} attached above.` },
  { value: 'team', label: 'Every published team skill this agent has the tools for (default)', hint: () => 'A skill naming a tool or knowledge base the agent lacks is shown locked.' },
  { value: 'off', label: 'None', hint: () => 'No / menu in chats with this agent.' },
];

/** Which skills a person may pick with / in a chat with this agent; saved with the version like every setting. */
export function SkillMenuSection({ draft, set, attached }: { draft: AgentDraft; set: (k: 'skillMenu', v: SkillMenu) => void; attached: number }) {
  return (
    <SettingsSection title="Team skills people can pick with /" description="A pick loads the skill for one reply; it is never attached.">
      <RadioGroup value={draft.skillMenu} onValueChange={(v) => set('skillMenu', v as SkillMenu)} className="gap-3" data-testid="agent-skill-menu">
        {CHOICES.map((c) => (
          <div key={c.value} className="flex items-start gap-2">
            <RadioGroupItem id={`skill-menu-${c.value}`} value={c.value} className="mt-0.5" />
            <div>
              <Label htmlFor={`skill-menu-${c.value}`}>{c.label}</Label>
              <p className="text-xs text-muted-foreground">{c.hint(attached)}</p>
            </div>
          </div>
        ))}
      </RadioGroup>
    </SettingsSection>
  );
}
