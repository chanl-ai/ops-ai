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

const connectorsKey = (threadId: string) => ['chat', 'connectors', threadId] as const;

/** The connectors this chat may use, for the composer's picker; asked again when it opens, since sign-ins change. */
export const useChatConnectors = (threadId: string | undefined, enabled = true) =>
  useTeamQuery({ queryKey: connectorsKey(threadId ?? ''), queryFn: () => api.chat.settings.connectors(threadId!), enabled: !!threadId && enabled, refetchOnMount: 'always' });

/** Sets which connectors the chat leaves out; the settings panel's tools follow, so they are read again. */
export function useSetChatConnectors(threadId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (off: string[]) => api.chat.settings.setConnectors(threadId, off),
    onSuccess: (answer) => {
      qc.setQueryData(teamKey(connectorsKey(threadId)), answer);
      void qc.invalidateQueries({ queryKey: teamKey(key(threadId)) });
    },
  });
}

/** A new chat's connectors before it exists, for the picker on Chat's home; every one starts on. */
export const useNewChatConnectors = (agentId: string | undefined, enabled = true) =>
  useTeamQuery({ queryKey: ['chat', 'connectors', 'new', agentId ?? ''], queryFn: () => api.chat.settings.newChatConnectors(agentId), enabled, refetchOnMount: 'always' });

/** Puts the connectors chosen on Chat's home onto the chat just made, before its first message is sent. */
export const useApplyChatConnectors = () =>
  useMutation({ mutationFn: ({ threadId, off }: { threadId: string; off: string[] }) => api.chat.settings.setConnectors(threadId, off) });
