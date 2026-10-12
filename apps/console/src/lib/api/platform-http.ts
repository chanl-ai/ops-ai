import type { Team } from '@/lib/types/team';

import type { OpsApi } from './contract';
import { createTransport } from './http';

/**
 * The teams a person signed in through platform-service belongs to (GET /v1/teams). Their token already names every
 * one of them, so switching changes only the X-Team-Id the console sends. Teams are created by an admin in platform
 * settings, so there is no create.
 */
export function createPlatformTeamsHttp(baseUrl: string): OpsApi['teams'] {
  const { get } = createTransport(`${baseUrl}/v1`);
  return {
    list: async () => (await get<Omit<Team, 'icon'>[]>('/teams')).map((t) => ({ ...t, icon: 'team' as const })),
  };
}
