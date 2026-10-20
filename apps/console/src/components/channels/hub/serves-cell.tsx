'use client';

import Link from 'next/link';
import { toast } from 'sonner';

import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useChangeChannel } from '@/hooks/channel-queries';
import type { ChannelRow } from '@/lib/types/channels';

const versionsOf = (latest: number) => Array.from({ length: latest }, (_, i) => latest - i);
const versionText = (version: 'latest' | number, latest: number, behind: number) => (version === 'latest' ? `Latest · v${latest}` : `v${version} pinned${behind ? ` · ${behind} behind` : ''}`);

/**
 * What a channel serves, in its row. A chat embed keeps its agent and changes its version in place: Latest, or a pinned
 * one. An email follows the live version of the workflow its trigger names (changed on that workflow), and an API key
 * runs whatever its team may (c-246 binds a key to one target).
 */
export function ServesCell({ channel }: { channel: ChannelRow }) {
  const change = useChangeChannel();
  const s = channel.serves;
  if (channel.type === 'api') return <span className="text-muted-foreground">Any of {channel.teamName}’s workflows</span>;
  if (!s) return <span className="text-muted-foreground">Nothing yet</span>;
  const label = (
    <span className="block truncate" onClick={(e) => e.stopPropagation()}>
      <Link href={s.kind === 'agent' ? `/agents/${encodeURIComponent(s.id)}?tab=channels` : `/workflows/${encodeURIComponent(s.id)}`} className="underline-offset-4 hover:underline">
        {s.name}
      </Link>
    </span>
  );
  if (channel.type !== 'chat' || !channel.canEdit)
    return (
      <span className="min-w-0">
        {label}
        <span className="block text-xs text-muted-foreground">
          {versionText(s.version, s.latestVersion, s.behind)}
          {channel.servesCount && channel.servesCount > 1 ? ` · and ${channel.servesCount - 1} more` : ''}
        </span>
      </span>
    );
  const choose = async (v: string) => {
    const version = v === 'latest' ? ('latest' as const) : Number(v);
    try {
      const out = await change.mutateAsync({ id: channel.id, patch: { serves: { kind: 'agent', id: s.id, version } } });
      if ('reviewId' in out) toast.info('The change waits for a review', { description: `Your team reviews what a channel serves. It applies once it is approved in Human Tasks.` });
      else toast.success(`${channel.name} now serves ${s.name} · ${version === 'latest' ? 'latest' : `v${version} pinned`}`);
    } catch (e) {
      toast.error('Couldn’t change the version', { description: (e as Error).message });
    }
  };
  return (
    // A row opens its channel on click; choosing here does not.
    <div className="flex min-w-0 items-center gap-2" onClick={(e) => e.stopPropagation()} data-testid={`serves-${channel.id}`}>
      <span className="min-w-0 max-w-40">{label}</span>
      <Select value={String(s.version)} onValueChange={choose} disabled={change.isPending}>
        <SelectTrigger size="sm" className="w-auto shrink-0" aria-label={`Version ${channel.name} serves`}>
          <SelectValue>{versionText(s.version, s.latestVersion, s.behind)}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="latest">Latest · v{s.latestVersion}</SelectItem>
          <SelectSeparator />
          {versionsOf(s.latestVersion).map((v, i) => (
            <SelectItem key={v} value={String(v)}>
              v{v} pinned{i > 0 ? ` · ${i} behind` : ''}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
