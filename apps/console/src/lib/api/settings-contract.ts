import type { BulkResult } from '@/lib/types/domain';
import type { ListParams, ListResult } from '@/lib/types/query';
import type {
  ApiKey,
  ApiKeyInput,
  DeliveryFilters,
  InviteInput,
  Member,
  MemberFilters,
  MemberRole,
  NotificationSettings,
  NotificationSettingsInput,
  SettingsLookups,
  UsageDays,
  UsageReport,
  Webhook,
  WebhookDelivery,
  WebhookInput,
} from '@/lib/types/settings';

/** Settings for the current team. The Platform team sees members and usage across every team. */
export interface SettingsApi {
  members: {
    list(params: ListParams<MemberFilters>): Promise<ListResult<Member>>;
    invite(input: InviteInput): Promise<BulkResult>;
    setRole(ids: string[], role: MemberRole): Promise<BulkResult>;
    remove(ids: string[]): Promise<BulkResult>;
  };
  notifications: {
    get(): Promise<NotificationSettings>;
    /** Rejects with 409 when someone saved a newer version. */
    update(input: NotificationSettingsInput): Promise<NotificationSettings>;
  };
  webhooks: {
    list(params: ListParams): Promise<ListResult<Webhook>>;
    create(input: WebhookInput): Promise<Webhook>;
    setStatus(id: string, status: 'active' | 'paused'): Promise<Webhook>;
    remove(id: string): Promise<void>;
    deliveries(id: string, params: ListParams<DeliveryFilters>): Promise<ListResult<WebhookDelivery>>;
    /** Sends a failed delivery's payload again as a new delivery. */
    resend(id: string, deliveryId: string): Promise<WebhookDelivery>;
  };
  apiKeys: {
    list(params: ListParams): Promise<ListResult<ApiKey>>;
    /** The full key is returned once and never again. */
    create(input: ApiKeyInput): Promise<{ key: string; apiKey: ApiKey }>;
    revoke(id: string): Promise<void>;
  };
  usage: {
    get(days: UsageDays): Promise<UsageReport>;
  };
  lookups(): Promise<SettingsLookups>;
}
