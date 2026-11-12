/** A policy value: a switch, a number (a threshold, days, hours), null for none, a list of names, or a per-area map (publish review). */
export type PolicyValue = boolean | number | string | null | string[] | Record<string, unknown>;

/** One workspace access policy as platform-service serves it (GET /v1/policies). Every default is open. */
/** How a policy's value is set: a switch, a confidence floor, a number of days or hours, or a mode per area. */
export type PolicyKind = 'bool' | 'floor' | 'days' | 'hours' | 'publish_modes' | 'names' | 'choice' | 'app_changes' | 'app_changes_by_app';

export interface WorkspacePolicy {
  key: string;
  /** The server's: the page draws each policy from it, so a new one needs no console change. */
  kind?: PolicyKind;
  title?: string;
  value: PolicyValue;
  default: PolicyValue;
  /** The grid cell a change needs, such as settings.manage. */
  changedBy: string;
  /** One line saying what the policy does. */
  effect: string;
  /** A `choice` policy's options, in order, each with what it means. */
  choices?: { value: string; title: string; description?: string }[];
  /** A fact the choice never changes, said under it (such as: private addresses are never allowed). */
  note?: string;
}

/**
 * What the person may do in the team they act in, from GET /v1/me/permissions: for each grid cell (`area.action`, such
 * as `settings.manage`) the roles that grant it. A policy names the cell its change needs in `changedBy`.
 */
export interface PolicyEditor {
  cells: Record<string, string[]>;
}
