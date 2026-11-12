'use client';

import * as React from 'react';
import { LayoutTemplate, Pin, Sparkles } from 'lucide-react';
import { toast } from 'sonner';

import type { AgentDraft } from '@/components/agents/agent-settings';
import { SaveAsTemplateDialog } from '@/components/agents/save-as-template-dialog';
import { initialSpec, PromptGeneratorDialog } from '@/components/prompts/prompt-generator-dialog';
import { Button } from '@/components/ui/button';
import { DropdownMenuItem } from '@/components/ui/dropdown-menu';
import { usePromptGenerator } from '@/hooks/prompt-queries';
import { useSubmitTemplate } from '@/hooks/template-queries';
import type { Agent, GrantableTool } from '@/lib/types/domain';
import type { AgentSkillPin } from '@/lib/types/skills';

/**
 * The agent page's prompt tooling: the generator and "Attach always-on skill" on the Instructions field, the
 * always-on skills that add to every turn under it, and "Save as template" for the page menu. Returned as slots so
 * the page only places them. Shared wording (disclosures, tone, policy rules) is an always-on skill, never text
 * pasted into the instructions.
 */
export function useInstructionsAssist({
  agent,
  draft,
  setInstructions,
  tools,
  dirty,
  alwaysOn,
  onAttachAlways,
}: {
  agent: Agent;
  draft: AgentDraft;
  setInstructions: (text: string) => void;
  tools: GrantableTool[];
  dirty: boolean;
  /** Always-on skills the agent pins. */
  alwaysOn: AgentSkillPin[];
  onAttachAlways: () => void;
}) {
  const generator = usePromptGenerator();
  const submit = useSubmitTemplate();
  const [genOpen, setGenOpen] = React.useState(false);
  const [templateOpen, setTemplateOpen] = React.useState(false);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const granted = tools.filter((t) => draft.toolIds.includes(t.id)).map((t) => t.name);
  const next = agent.version + 1;

  const toolbar = (
    <>
      <Button variant="outline" size="sm" className="bg-card" onClick={onAttachAlways} data-testid="attach-always-skill">
        <Pin className="size-3.5" /> Attach always-on skill
      </Button>
      <Button variant="outline" size="sm" className="bg-card" onClick={() => setGenOpen(true)} data-testid="generate-instructions">
        <Sparkles className="size-3.5" /> Generate instructions
      </Button>
    </>
  );
  const footer = alwaysOn.length ? (
    <p className="text-xs text-muted-foreground" data-testid="always-on-footer">
      Added to every turn after these instructions: {alwaysOn.map((p) => `${p.name} v${p.pinnedVersion}`).join(', ')}.
    </p>
  ) : null;

  const menuItem = (
    <DropdownMenuItem onClick={() => setTemplateOpen(true)}>
      <LayoutTemplate className="size-4" /> Save as template
    </DropdownMenuItem>
  );

  const dialogs = (
    <>
      <PromptGeneratorDialog
        open={genOpen}
        onOpenChange={setGenOpen}
        backend={generator}
        context={{ model: draft.model, grantedTools: granted, collections: draft.collections }}
        initial={initialSpec({ role: draft.role, channels: draft.channels, tools: granted, collections: draft.collections, guardrails: draft.guardrails })}
        currentInstructions={draft.instructions}
        onApply={(text) => {
          setInstructions(text);
          toast.success('Instructions replaced', { description: `Not saved yet. Saving creates v${next}, a re-test change: evals run on it before any workflow adopts it.` });
        }}
        applyNote={`Applying replaces the Instructions field. Save as v${next} to keep it; that is a re-test change, so evals run on the new version.`}
      />
      <SaveAsTemplateDialog
        open={templateOpen}
        onOpenChange={setTemplateOpen}
        agentId={agent.id}
        agentName={agent.name}
        version={agent.version}
        dirty={dirty}
        isPending={submit.isPending}
        onSubmit={async (input) => {
          const t = await submit.mutateAsync(input);
          toast.success(`Sent ${t.name} for review`, { description: 'The platform team reviews it before other teams can use it. It shows as In review under Agents → Templates.' });
        }}
      />
    </>
  );

  return { toolbar, footer, menuItem, dialogs, textareaRef };
}
