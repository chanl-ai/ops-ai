import type { BulkResult } from '@/lib/types/domain';
import type {
  CatalogSystem,
  ConnectInput,
  ConnectionSetupPatch,
  DraftConnectInput,
  ConnectionRef,
  Integration,
  IntegrationDetail,
  IntegrationFilters,
  IntegrationView,
  IntegrationViewCounts,
  RevokeImpact,
} from '@/lib/types/integrations';
import type { ListParams, ListResult } from '@/lib/types/query';

/** Connections to bank systems, scoped to the current team. Every connect, revoke, rotate and scope change is audited. */
export interface IntegrationsApi {
  list(params: ListParams<IntegrationFilters> & { view: IntegrationView }): Promise<ListResult<Integration> & { viewCounts: IntegrationViewCounts }>;
  get(id: string): Promise<IntegrationDetail>;
  /** Every connection the team can pick when adding a source, tool module or mailbox. */
  options(): Promise<ConnectionRef[]>;
  catalog(): Promise<CatalogSystem[]>;
  connect(input: ConnectInput): Promise<Integration>;
  /** Saves a draft connection from the one-screen connect; it serves nothing until `activate`. */
  createDraft(input: DraftConnectInput): Promise<Integration>;
  /** Drafts only: saves scopes, credential, owner or expiry from the Setup tab. 409 once active. */
  saveSetup(id: string, patch: ConnectionSetupPatch): Promise<IntegrationDetail>;
  /** Runs the connect checks on a draft (scopes, sign-in, owner, expiry) and makes it live. 400 names what is missing. */
  activate(id: string): Promise<IntegrationDetail>;
  /** Renews consent or re-establishes the credential; dependants resume. */
  reconnect(id: string): Promise<IntegrationDetail>;
  /** Points the connection at a new vault path; the gateway uses it from the next call. */
  rotate(id: string, credentialRef: string): Promise<IntegrationDetail>;
  check(id: string): Promise<IntegrationDetail>;
  bulkCheck(ids: string[]): Promise<BulkResult>;
  /** What stops working if these connections are revoked. */
  impact(ids: string[]): Promise<RevokeImpact>;
  revoke(ids: string[], reason: string): Promise<BulkResult>;
  /** Opens a request the system owner decides; nothing is granted until then. */
  requestScopes(id: string, input: { scopes: string[]; justification: string }): Promise<IntegrationDetail>;
  /** The two switches on a Connections row: sync knowledge from the system, and expose its operations as tools. */
  setSwitches(id: string, patch: { syncKnowledge?: boolean; exposeTools?: boolean }): Promise<Integration>;
}
