import type { SourceKindOption } from '@/lib/types/knowledge';

/** The kinds that get a "Connect it on its app page" link: an app that is on but has no working connection. A kind
 *  refused because its connection signs in each person is not fixed by connecting, so it gets no link. */
export function kindsToConnect<T extends Pick<SourceKindOption, 'needsConnection' | 'connected' | 'cannotCreateCode' | 'plugin'>>(options: T[]): T[] {
  return options.filter((k) => k.needsConnection && !k.connected && k.cannotCreateCode !== 'sign_in_not_team' && !!k.plugin);
}
