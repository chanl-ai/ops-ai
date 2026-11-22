'use client';

import * as React from 'react';
import { LayoutTemplate, Pin } from 'lucide-react';
import { toast } from 'sonner';

import { SaveAsTemplateDialog } from '@/components/agents/save-as-template-dialog';
import { Button } from '@/components/ui/button';
import { DropdownMenuItem } from '@/components/ui/dropdown-menu';
import { useSubmitTemplate } from '@/hooks/template-queries';
import type { Agent } from '@/lib/types/domain';
import type { AgentSkillPin } from '@/lib/types/skills';

/**
 * The agent page's prompt tooling: "Attach always-on skill" on the plain-text Instructions field, the
 * always-on skills that add to every turn under it, and "Save as template" for the page menu. Returned as slots so
 * the page only places them. Shared wording (disclosures, tone, policy rules) is an always-on skill, never text
 * pasted into the instructions.
 */
export function useInstructionsAssist({
  agent,
  dirty,
  alwaysOn,
  onAttachAlways,
}: {
  agent: Agent;
  dirty: boolean;
  /** Always-on skills the agent pins. */
  alwaysOn: AgentSkillPin[];
  onAttachAlways: () => void;
}) {
  const submit = useSubmitTemplate();
  const [templateOpen, setTemplateOpen] = React.useState(false);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  const toolbar = (
      <Button variant="outline" size="sm" className="bg-card" onClick={onAttachAlways} data-testid="attach-always-skill">
        <Pin className="size-3.5" /> Attach skill
      </Button>
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
