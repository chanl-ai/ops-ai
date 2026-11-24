/**
 * Policies Governance › Policies does not list: the approval rules are set on Approvals (the old keys are derived from
 * them), `requesterMayDecide` is retired (the Approvals · decide cell on the Roles page decides who approves their own
 * requests), and `approvalsFloor` has no editor until its own screen ships (the generic switch cannot send its object).
 */
const NOT_ON_POLICIES = new Set(['appChanges', 'appChangesByApp', 'toolWritesNeedApproval', 'appWritesNeedApproval', 'appsChangeWithoutAsking', 'requesterMayDecide', 'approvalsFloor']);

export const listedOnPolicies = (key: string) => !NOT_ON_POLICIES.has(key);
