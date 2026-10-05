'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ListParams } from '@/lib/types/query';
import type { ApiKeyInput, DeliveryFilters, InviteInput, MemberFilters, MemberRole, NotificationSettingsInput, UsageDays, WebhookInput } from '@/lib/types/settings';

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

export const useMembers = (p: ListParams<MemberFilters>) => useQuery({ queryKey: sk.members(p), queryFn: () => api.settings.members.list(p), placeholderData: keepPreviousData });
export const useNotificationSettings = () => useQuery({ queryKey: sk.notifications, queryFn: api.settings.notifications.get });
export const useWebhooks = (p: ListParams) => useQuery({ queryKey: sk.webhooks(p), queryFn: () => api.settings.webhooks.list(p), placeholderData: keepPreviousData });
export const useWebhookDeliveries = (id: string | null, p: ListParams<DeliveryFilters>) =>
  useQuery({ queryKey: sk.deliveries(id ?? '', p), queryFn: () => api.settings.webhooks.deliveries(id!, p), enabled: !!id, placeholderData: keepPreviousData });
export const useApiKeys = (p: ListParams) => useQuery({ queryKey: sk.keys(p), queryFn: () => api.settings.apiKeys.list(p), placeholderData: keepPreviousData });
export const useUsage = (days: UsageDays) => useQuery({ queryKey: sk.usage(days), queryFn: () => api.settings.usage.get(days), placeholderData: keepPreviousData });
export const useSettingsLookups = () => useQuery({ queryKey: sk.lookups, queryFn: api.settings.lookups, staleTime: 5 * 60_000 });

function useSettingsWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => Promise.all(['settings', 'logs'].map((r) => qc.invalidateQueries({ queryKey: [r] }))) });
}

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
