'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ChatOverridesPatch } from '@/lib/types/chat';
import { teamKey, useTeamQuery } from './team-query';

const key = (threadId: string) => ['chat', 'settings', threadId] as const;

/** What the thread's agent lets the banker change, the thread's overrides, and the settings turns start from. */
export const useThreadSettings = (threadId: string | undefined, enabled = true) =>
  useTeamQuery({ queryKey: key(threadId ?? ''), queryFn: () => api.chat.settings.get(threadId!), enabled: !!threadId && enabled });

/** Saving merges into the thread's overrides; a value outside the limits fails with the field it names. */
export function useSaveThreadSettings(threadId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: ChatOverridesPatch) => api.chat.settings.save(threadId, patch),
    onSuccess: (settings) => qc.setQueryData(teamKey(key(threadId)), settings),
  });
}
