'use client';

import { plural } from '@/lib/format';
import type { AgentUses } from '@/lib/types/domain';

const LINKED = [
  ['tools', 'tool', '#agent-tools'],
  ['knowledgeBases', 'knowledge base', '#agent-knowledge'],
  ['skills', 'skill', '#agent-skills'],
] as const;

/**
 * "Uses 3 tools · 2 knowledge bases · 3 skills" in the brief card's header row: each count is a link down to its section
 * on the same page, from the service's counts, with a kind left out when it is zero.
 */
export function AgentUsesLink({ uses }: { uses: AgentUses | undefined }) {
  const parts = [
    ...LINKED.filter(([k]) => uses?.[k]).map(([k, noun, href]) => (
      <a key={k} href={href} className="underline-offset-4 hover:text-foreground hover:underline" data-testid={`agent-uses-${k}`}>
        {plural(uses![k], noun)}
      </a>
    )),
    ...(uses?.agents ? [<span key="agents">{plural(uses.agents, 'agent')}</span>] : []),
    ...(uses?.workflows ? [<span key="workflows">{plural(uses.workflows, 'workflow')}</span>] : []),
  ];
  return (
    <p className="text-xs text-muted-foreground" data-testid="agent-uses-link">
      {parts.length ? (
        <>
          Uses{' '}
          {parts.map((p, i) => (
            <span key={i}>
              {i > 0 && ' · '}
              {p}
            </span>
          ))}
        </>
      ) : (
        'Uses nothing yet'
      )}
    </p>
  );
}
