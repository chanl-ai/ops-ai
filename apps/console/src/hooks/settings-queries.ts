'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api, invitesToCurrentTeam } from '@/lib/api';
import type { ListParams } from '@/lib/types/query';
import type { ApiKeyInput, DeliveryFilters, InviteInput, MemberFilters, MemberRole, NotificationSettingsInput, UsageDays, WebhookInput } from '@/lib/types/settings';
import { useTeamQuery } from './team-query';

/** Every settings key starts with 'settings'; writes also refresh the audit log ('logs'). */
export const sk = {
  members: (p: unknown) => ['settings', 'members', p] as const,
  notifications: ['settings', 'notifications'] as const,
  webhooks: (p: unknown) => ['settings', 'webhooks', p] as const,
  deliveries: (id: string, p: unknown) => ['settings', 'webhooks', id, 'deliveries', p] as const,
  keys: (p: unknown) => ['settings', 'keys', p] as const,
  usage: (days: number) => ['settings', 'usage', days] as const,
  lookups: ['settings', 'lookups'] as const,
};

export const useMembers = (p: ListParams<MemberFilters>) => usePagedQuery({ queryKey: sk.members(p), queryFn: () => api.settings.members.list(p) });
export const useNotificationSettings = () => useTeamQuery({ queryKey: sk.notifications, queryFn: api.settings.notifications.get });
export const useWebhooks = (p: ListParams) => usePagedQuery({ queryKey: sk.webhooks(p), queryFn: () => api.settings.webhooks.list(p) });
export const useWebhookDeliveries = (id: string | null, p: ListParams<DeliveryFilters>) =>
  usePagedQuery({ queryKey: sk.deliveries(id ?? '', p), queryFn: () => api.settings.webhooks.deliveries(id!, p), enabled: !!id });
export const useApiKeys = (p: ListParams) => usePagedQuery({ queryKey: sk.keys(p), queryFn: () => api.settings.apiKeys.list(p) });
export const useUsage = (days: UsageDays) => usePagedQuery({ queryKey: sk.usage(days), queryFn: () => api.settings.usage.get(days) });
export const useSettingsLookups = () => useTeamQuery({ queryKey: sk.lookups, queryFn: api.settings.lookups, staleTime: 5 * 60_000 });

function useSettingsWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => Promise.all(['settings', 'logs'].map((r) => qc.invalidateQueries({ queryKey: [r] }))) });
}

/** True when an invitation always goes to the team the person is working as, so the invite dialog offers no team. */
export const useInvitesToCurrentTeam = () => invitesToCurrentTeam;
export const useInviteMembers = () => useSettingsWrite((i: InviteInput) => api.settings.members.invite(i));
export const useSetMemberRole = () => useSettingsWrite(({ ids, role }: { ids: string[]; role: MemberRole }) => api.settings.members.setRole(ids, role));
export const useRemoveMembers = () => useSettingsWrite((ids: string[]) => api.settings.members.remove(ids));
export const useSaveNotifications = () => useSettingsWrite((i: NotificationSettingsInput) => api.settings.notifications.update(i));
export const useCreateWebhook = () => useSettingsWrite((i: WebhookInput) => api.settings.webhooks.create(i));
export const useSetWebhookStatus = () => useSettingsWrite(({ id, status }: { id: string; status: 'active' | 'paused' }) => api.settings.webhooks.setStatus(id, status));
export const useResendDelivery = () => useSettingsWrite(({ id, deliveryId }: { id: string; deliveryId: string }) => api.settings.webhooks.resend(id, deliveryId));
export const useDeleteWebhook = () => useSettingsWrite((id: string) => api.settings.webhooks.remove(id));
export const useCreateApiKey = () => useSettingsWrite((i: ApiKeyInput) => api.settings.apiKeys.create(i));
export const useRevokeApiKey = () => useSettingsWrite((id: string) => api.settings.apiKeys.revoke(id));
