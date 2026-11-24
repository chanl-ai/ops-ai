'use client';

import * as React from 'react';
import Link from 'next/link';
import { ChevronDown, Layers } from 'lucide-react';
import { toast } from 'sonner';

import { Row, Rows, Section } from '@/components/shared/surface';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { useCreateSkill } from '@/hooks/skill-queries';
import { plural } from '@/lib/format';
import type { SkillPartContent } from '@/lib/types/skills';

/**
 * A skill's parts, read-only under its instructions. A part has its own name, use-when line, instructions and tools, so
 * each works as its own skill; none are edited here, and Open shows what one says. Split skills makes one skill of each
 * part through the skills create route, in the skill's own team; the parts stay where they are.
 */
export function PartsList({ parts, ownerTeam, knowledgeBases, canSplit }: { parts: readonly SkillPartContent[]; ownerTeam: string; knowledgeBases: string[]; canSplit: boolean }) {
  const [open, setOpen] = React.useState<string | null>(null);
  const create = useCreateSkill();
  const [made, setMade] = React.useState<string[]>([]);
  const split = async () => {
    const done: string[] = [];
    try {
      for (const p of parts) {
        const s = await create.mutateAsync({ name: p.name, useWhen: p.useWhen, instructions: p.instructions, ownerTeam, toolIds: p.toolIds, knowledgeBases, guardrails: [], origin: 'duplicated' });
        done.push(s.name);
      }
      setMade(done);
      toast.success(`Made ${plural(done.length, 'skill')} from the parts`, { description: 'Find them in Skills, each a draft to review and publish.' });
    } catch (e) {
      setMade(done);
      toast.error(done.length ? `Made ${plural(done.length, 'skill')}, then stopped` : 'No skill was made', { description: e instanceof Error ? e.message : 'Try again.' });
    }
  };
  return (
    <Section
      flush
      title={
        <span className="flex items-center gap-2">
          <Layers className="size-4 text-muted-foreground" aria-hidden /> Parts
          <span className="font-normal text-muted-foreground tabular-nums">{parts.length}</span>
        </span>
      }
      description={`This skill has ${plural(parts.length, 'part')}. Each works as its own skill. Split skills to edit them.`}
      actions={
        canSplit && (
          <Button variant="outline" size="sm" onClick={() => void split()} disabled={create.isPending || made.length > 0} data-testid="skill-parts-split">
            Split skills
          </Button>
        )
      }
    >
      {made.length > 0 && (
        <p className="border-b px-4 py-2 text-sm" data-testid="skill-parts-made">
          Made {plural(made.length, 'skill')}: {made.join(', ')}. This skill still has its own parts, so an agent that uses it is unchanged. <Link href="/build/skills" className="underline">Open Skills</Link>
        </p>
      )}
      <Rows testId="skill-parts">
        {parts.map((p) => (
          <Collapsible key={p.slug} open={open === p.slug} onOpenChange={(o) => setOpen(o ? p.slug : null)}>
            <Row
              wrap
              title={p.name}
              description={p.useWhen || undefined}
              trailing={
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="sm" data-testid="skill-part-open">
                    Open <ChevronDown className={open === p.slug ? 'size-3.5 rotate-180' : 'size-3.5'} />
                  </Button>
                </CollapsibleTrigger>
              }
            >
              <CollapsibleContent>
                <pre className="mt-1 max-h-60 overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-xs whitespace-pre-wrap">{p.instructions}</pre>
              </CollapsibleContent>
            </Row>
          </Collapsible>
        ))}
      </Rows>
    </Section>
  );
}
