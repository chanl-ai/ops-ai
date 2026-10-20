'use client';

import { RouteTabs } from '@/components/shared/route-tabs';
import type { ChannelKindSummary } from '@/lib/types/channels';
import { cn } from '@/lib/utils';

import { HEALTH_DOT, HEALTH_WORD, KINDS } from './kinds';

/** Overview, then a tab per kind with a dot for its health; kinds coming soon carry no dot. */
export function ChannelTabs({ kinds }: { kinds: ChannelKindSummary[] | undefined }) {
  const tabs = [
    { href: '/channels', label: 'Overview' },
    ...KINDS.map((k) => {
      const summary = kinds?.find((s) => s.type === k.type);
      const built = summary?.built ?? ['email', 'chat', 'api'].includes(k.type);
      const health = summary?.health ?? 'idle';
      return {
        href: k.href,
        label: (
          <span className="inline-flex items-center gap-1.5" data-testid={`channel-tab-${k.type}`} data-health={built ? health : 'soon'}>
            {built && <span aria-hidden="true" className={cn('size-1.5 rounded-full', HEALTH_DOT[health])} />}
            {k.title}
            <span className="sr-only">{built ? `, ${HEALTH_WORD[health].toLowerCase()}` : ', coming soon'}</span>
          </span>
        ),
      };
    }),
  ];
  return <RouteTabs tabs={tabs} />;
}
