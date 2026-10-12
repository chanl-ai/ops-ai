/**
 * What a person reads when models-service refused the model call behind a reply. The chat stream's error frame carries
 * the refusal `code`; the service's own message names keys and limits meant for operators.
 */
const REFUSALS: Record<string, string> = {
  rate_limited: 'The model is rate limited. Wait a minute and retry.',
  key_budget_exhausted: "This agent's model budget is spent. An admin can raise it in Models.",
  key_revoked: "This agent's model key was revoked. An admin can issue a new one in Models.",
  key_expired: "This agent's model key expired. An admin can issue a new one in Models.",
  key_not_registered: 'This agent has no model key. An admin can issue one in Models.',
  invalid_key: 'The model key was not accepted. An admin can check it in Models.',
  sensitivity_not_cleared: 'This model is not cleared for data this sensitive. Choose a model cleared for it.',
  alias_not_found: "This agent's model is no longer offered. Choose another model on the agent page.",
  unknown_model_alias: "This agent's model is no longer offered. Choose another model on the agent page.",
  provider_error: 'The model provider did not answer. Retry in a moment.',
};

export function modelRefusalText(code: string | undefined): string | undefined {
  return code ? REFUSALS[code] : undefined;
}
