/**
 * What a person reads when models-service refused the model call behind a reply, by the refusal's `code`: what happened,
 * then what to do, worded for the reader. A person who manages settings is told to fix it; anyone else is told whom to
 * ask. The service's own message (shown for a code not listed here) names keys and limits meant for operators.
 */
interface Refusal {
  said: string;
  /** What anyone does; set when the fix is the same for every reader. */
  anyone?: string;
  /** What a person who manages settings does, and what anyone else does. */
  admin?: string;
  member?: string;
  /** Where the admin's fix is, offered as a link to them only. */
  fixAt?: string;
}

export const MODEL_PROVIDERS_HREF = '/settings/workspace/model-providers';

const REFUSALS: Record<string, Refusal> = {
  rate_limited: { said: "This agent is over its model key's calls a minute.", anyone: 'Wait a minute and retry.' },
  key_budget_exhausted: { said: "This agent's model budget is spent.", admin: 'Raise it in Models.', member: 'Ask an admin to raise it in Models.' },
  key_revoked: { said: "This agent's model key was revoked.", admin: 'Issue a new one in Models.', member: 'Ask an admin to issue a new one in Models.' },
  key_expired: { said: "This agent's model key expired.", admin: 'Issue a new one in Models.', member: 'Ask an admin to issue a new one in Models.' },
  key_not_registered: { said: 'This agent has no model key.', admin: 'Issue one in Models.', member: 'Ask an admin to issue one in Models.' },
  invalid_key: { said: 'The model key was not accepted.', admin: 'Check it in Models.', member: 'Ask an admin to check it in Models.' },
  sensitivity_not_cleared: { said: 'This model is not cleared for data this sensitive.', anyone: 'Choose a model cleared for it.' },
  alias_not_found: { said: "This agent's model is no longer offered.", anyone: 'Choose another model on the agent page.' },
  unknown_model_alias: { said: "This agent's model is no longer offered.", anyone: 'Choose another model on the agent page.' },
  provider_key_missing: {
    said: 'The account has not saved the key this model signs in with.',
    admin: 'Add it on Settings > Model providers.',
    member: 'Ask an admin to add it on Settings > Model providers.',
    fixAt: MODEL_PROVIDERS_HREF,
  },
  provider_auth_failed: {
    said: "The model provider refused the account's key.",
    admin: 'Check or replace the key on Settings > Model providers.',
    member: 'Ask an admin to check the key on Settings > Model providers.',
    fixAt: MODEL_PROVIDERS_HREF,
  },
  provider_unreachable: {
    said: 'The model provider could not be reached.',
    admin: 'Check the connection on Settings > Model providers, then retry.',
    member: 'Retry in a moment. If it keeps happening, ask an admin to check Settings > Model providers.',
    fixAt: MODEL_PROVIDERS_HREF,
  },
  provider_bad_request: {
    said: 'The model provider refused the request: the model or deployment name, or a setting, may be wrong.',
    admin: 'Check the model on Settings > Model providers.',
    member: 'Ask an admin to check the model on Settings > Model providers.',
    fixAt: MODEL_PROVIDERS_HREF,
  },
  provider_rate_limited: {
    said: "The model provider is limiting calls on the account's key.",
    admin: 'Wait a minute and retry. If it keeps happening, raise the limit with the provider.',
    member: 'Wait a minute and retry.',
  },
  provider_timeout: { said: 'The model provider did not answer in time.', anyone: 'Retry in a moment.' },
  provider_error: { said: 'The model provider failed to answer.', anyone: 'Retry in a moment.' },
  guardrail_unavailable: { said: "This agent's guardrails could not be checked, so the question was not answered.", anyone: 'Retry in a moment.' },
};

/**
 * The refusal behind `code` for a reader who manages settings (`admin`) or not: the sentence to show and, for an admin
 * whose fix is on a settings page, that page. Undefined for a code not listed, so the caller shows the service's own
 * message.
 */
export function modelRefusal(code: string | undefined, admin: boolean): { text: string; fixAt?: string } | undefined {
  const r = code ? REFUSALS[code] : undefined;
  if (!r) return undefined;
  const action = r.anyone ?? (admin ? r.admin : r.member);
  return { text: action ? `${r.said} ${action}` : r.said, fixAt: admin ? r.fixAt : undefined };
}
