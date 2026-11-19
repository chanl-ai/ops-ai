'use client';

import * as React from 'react';
import { FileText } from 'lucide-react';
import { toast } from 'sonner';

import { PageLayout } from '@/components/page-layout';
import { type DocumentValue, InstructionDocument, referencesIn } from '@/components/shared/instruction-document';
import { JsonBlock } from '@/components/shared/json-block';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { useReferenceLabels, useReferenceSearch } from '@/hooks/references-queries';
import type { ReferenceContext } from '@/lib/types/references';

import { BRIEF, BRIEF_PROBLEMS, SKILL, VARIABLES } from './sample';

/**
 * A test surface for the instruction document: an agent's brief and a skill's steps, with the stored value each edit
 * produces beside it. Reachable only where src/proxy.ts lets /dev through, and not in the nav.
 */
export default function InstructionDocumentPage() {
  const [readOnly, setReadOnly] = React.useState(false);
  return (
    <PageLayout
      icon={FileText}
      title="Instruction document"
      description="The shared editor for an agent's brief and a skill's steps, on sample data."
      actions={
        <div className="flex items-center gap-2">
          <Switch id="read-only" checked={readOnly} onCheckedChange={setReadOnly} />
          <Label htmlFor="read-only">Read only</Label>
        </div>
      }
    >
      <div className="flex flex-col gap-8">
        <Sample id="brief" title="Agent brief" context={{ forAgent: 'agt_dispute_desk' }} initial={BRIEF} readOnly={readOnly} agent />
        <Sample id="skill" title="Skill steps" context={{ forSkill: 'skl_chase_documents' }} initial={SKILL} readOnly={readOnly} />
      </div>
    </PageLayout>
  );
}

function Sample({ id, title, context, initial, readOnly, agent }: { id: string; title: string; context: ReferenceContext; initial: DocumentValue; readOnly: boolean; agent?: boolean }) {
  const [value, setValue] = React.useState(initial);
  const [gone, setGone] = React.useState<string[]>([]);
  const ids = React.useMemo(() => referencesIn(value).map((r) => `${r.kind}:${r.id}`), [value]);
  const labels = useReferenceLabels(context, ids);
  const search = useReferenceSearch(context);
  return (
    <div className="flex flex-col gap-3" data-testid={`sample-${id}`}>
      <h2 className="text-lg font-semibold">{title}</h2>
      <InstructionDocument
        label={title}
        value={value}
        onChange={setValue}
        searchReferences={search}
        resolved={labels.data}
        missing={agent ? BRIEF_PROBLEMS : undefined}
        onMissingChange={(refs) => setGone(refs.map((r) => `${r.kind}:${r.id}`))}
        onInsertReference={agent ? (ref) => void toast.success(`Asked to add ${ref.kind} ${ref.id} to the agent`) : undefined}
        variables={VARIABLES}
        readOnly={readOnly}
        footer={agent ? undefined : 'add-step'}
      />
      <p className="text-sm text-muted-foreground" data-testid={`missing-${id}`}>
        Missing: {gone.join(', ') || 'none'}
      </p>
      <div data-testid={`value-${id}`}>
        <JsonBlock value={value} maxHeight="20rem" wrap />
      </div>
    </div>
  );
}
