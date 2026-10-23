'use client';

import * as React from 'react';
import { Bot, Mail, User } from 'lucide-react';

import { Row, Rows, Section } from '@/components/shared/surface';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { dateTime, relativeTime } from '@/lib/format';
import type { StoryLine, StorySource } from '@/lib/types/engine';

const ICON: Record<StorySource, React.ReactNode> = {
  person: <User className="size-4 text-muted-foreground" />,
  automation: <Bot className="size-4 text-muted-foreground" />,
  email: <Mail className="size-4 text-muted-foreground" />,
};
const FILTERS: { value: 'all' | StorySource; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'person', label: 'People' },
  { value: 'automation', label: 'Automation' },
  { value: 'email', label: 'Email' },
];

/**
 * What a run or a case went through, one sentence per line, as the API words it (agents-service run_story.lines): the
 * run page and the case page draw the same lines through this, and no page words a step itself. `filters` adds People,
 * Automation and Email.
 */
export function StoryFeed({
  title,
  description,
  lines,
  more,
  filters,
  testId = 'story-feed',
}: {
  title: string;
  description?: string;
  lines: StoryLine[];
  more?: number;
  filters?: boolean;
  testId?: string;
}) {
  const [shown, setShown] = React.useState<'all' | StorySource>('all');
  const visible = shown === 'all' ? lines : lines.filter((l) => l.source === shown);
  return (
    <Section
      title={title}
      description={description}
      flush
      actions={
        filters ? (
          <ToggleGroup
            type="single"
            variant="outline"
            value={shown}
            onValueChange={(v) => v && setShown(v as typeof shown)}
            aria-label="Show"
            className="max-w-full overflow-x-auto"
            data-testid={`${testId}-filter`}
          >
            {FILTERS.map((f) => (
              <ToggleGroupItem key={f.value} value={f.value} className="flex-none px-3 whitespace-nowrap" data-testid={`${testId}-filter-${f.value}`}>
                {f.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        ) : undefined
      }
    >
      {visible.length ? (
        <Rows testId={testId}>
          {visible.map((l, i) => (
            <Row
              key={`${l.at}-${i}`}
              wrap
              leading={ICON[l.source] ?? ICON.automation}
              title={
                <span className="font-normal" data-testid={`${testId}-line`} data-source={l.source}>
                  {l.text}
                </span>
              }
              trailing={
                l.at ? (
                  <time className="text-xs text-muted-foreground" dateTime={l.at} title={dateTime(l.at)}>
                    {relativeTime(l.at)}
                  </time>
                ) : undefined
              }
              href={l.href ?? undefined}
            />
          ))}
        </Rows>
      ) : (
        <p className="px-4 py-3 text-sm text-muted-foreground" data-testid={`${testId}-empty`}>
          {lines.length ? 'Nothing of this kind happened.' : 'Nothing has happened yet.'}
        </p>
      )}
      {!!more && (
        <p className="border-t px-4 py-2 text-xs text-muted-foreground" data-testid={`${testId}-more`}>
          {more} earlier {more === 1 ? 'line is' : 'lines are'} not shown.
        </p>
      )}
    </Section>
  );
}
