'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { MailboxInput, MailboxPatch } from '@/lib/types/channels';
import { useTeamQuery } from './team-query';

const ck = {
  all: ['channels', 'mailboxes'] as const,
  list: (search: string) => ['channels', 'mailboxes', 'list', search] as const,
  one: (id: string) => ['channels', 'mailboxes', 'one', id] as const,
};

export const useMailboxes = (search = '') => useTeamQuery({ queryKey: ck.list(search), queryFn: () => api.channels.mailboxes(search) });

export const useMailbox = (id: string) => useTeamQuery({ queryKey: ck.one(id), queryFn: () => api.channels.mailbox(id), enabled: !!id, retry: false });

/** Connecting or editing a mailbox changes the list, the page and the trigger's mailbox picker. */
function useInvalidate() {
  const qc = useQueryClient();
  return () => Promise.all([qc.invalidateQueries({ queryKey: ck.all }), qc.invalidateQueries({ queryKey: ['engine', 'options', 'mailboxes'] })]);
}

export function useConnectMailbox() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (input: MailboxInput) => api.channels.connectMailbox(input), onSuccess: invalidate });
}

export function useEditMailbox(id: string) {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (patch: MailboxPatch) => api.channels.editMailbox(id, patch), onSuccess: invalidate });
}

export const useTestMailbox = () => useMutation({ mutationFn: (target: { input: MailboxInput } | { id: string }) => api.channels.testMailbox(target) });
