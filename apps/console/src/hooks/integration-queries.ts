'use client';

import { api } from '@/lib/api';

import { useTeamQuery } from './team-query';

/**
 * The connections a knowledge source can read through, for its Add source dialog. The rest of the sample integrations
 * API went with its pages (c-617): apps are connected and managed from the Apps pages over tools-service.
 */
export const useIntegrationOptions = (enabled = true) =>
  useTeamQuery({ queryKey: ['integrations', 'options'], queryFn: api.integrations.options, enabled });
