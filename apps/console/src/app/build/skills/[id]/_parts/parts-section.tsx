'use client';

import * as React from 'react';
import { ChevronDown, Layers } from 'lucide-react';

import { Row, Rows, Section } from '@/components/shared/surface';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import type { SkillPartContent } from '@/lib/types/skills';

/**
 * A skill's parts, read-only under its instructions. A part has its own name, use-when line, instructions and tools, so
 * each works as its own skill; none are added or edited here, and Open shows what one says until it is split.
 */
export function PartsList({ parts }: { parts: readonly SkillPartContent[] }) {
  const [open, setOpen] = React.useState<string | null>(null);
  return (
    <Section
      flush
      title={
        <span className="flex items-center gap-2">
          <Layers className="size-4 text-muted-foreground" aria-hidden /> Parts
          <span className="font-normal text-muted-foreground tabular-nums">{parts.length}</span>
        </span>
      }
      description={`This skill has ${parts.length === 1 ? '1 part' : `${parts.length} parts`}. Each works as its own skill. Split into skills to edit them.`}
    >
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
