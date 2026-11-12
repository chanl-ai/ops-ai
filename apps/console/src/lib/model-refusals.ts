/**
 * What a person reads when models-service refused the model call behind a reply, by the refusal's `code`: what happened,
 * then what to do, worded for the reader. A person who manages settings is told to fix it; anyone else is told whom to
 * ask. The service's own message names keys and limits meant for operators, so a code not listed here gets one plain
 * sentence and the code itself is kept for a details control.
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
  rate_limited: { said: 'This agent made too many model calls this minute.', anyone: 'Wait a minute and retry.' },
  key_budget_exhausted: { said: "This agent's model budget is spent.", admin: 'Open Model providers to see the saved keys, or ask whoever runs this install to raise the budget.', member: 'Ask an admin to raise it.', fixAt: MODEL_PROVIDERS_HREF },
  key_revoked: { said: "This agent's model key was revoked.", admin: 'Open Model providers to see the saved keys, or ask whoever runs this install to issue a new one.', member: 'Ask an admin to issue a new one.', fixAt: MODEL_PROVIDERS_HREF },
  key_expired: { said: "This agent's model key expired.", admin: 'Open Model providers to see the saved keys, or ask whoever runs this install to issue a new one.', member: 'Ask an admin to issue a new one.', fixAt: MODEL_PROVIDERS_HREF },
  key_not_registered: { said: 'This agent has no model key.', admin: 'Open Model providers to see the saved keys, or ask whoever runs this install to issue one.', member: 'Ask an admin to issue one.', fixAt: MODEL_PROVIDERS_HREF },
  invalid_key: { said: 'The model key was not accepted.', admin: 'Open Model providers to check the saved keys.', member: 'Ask an admin to check the key.', fixAt: MODEL_PROVIDERS_HREF },
  tenant_budget_exhausted: { said: "This team's share of the model budget is spent.", admin: 'Open Model providers, or ask whoever runs this install to raise it.', member: 'Ask an admin to raise it.', fixAt: MODEL_PROVIDERS_HREF },
  images_not_cleared: { said: 'This model is not cleared for images or files.', anyone: 'Choose a model cleared for them.' },
  sensitivity_not_cleared: { said: 'This model is not cleared for data this sensitive.', anyone: 'Choose a model cleared for it.' },
  alias_not_found: { said: "This agent's model is no longer offered.", anyone: 'Choose another model on the agent page.' },
  unknown_model_alias: { said: "This agent's model is no longer offered.", anyone: 'Choose another model on the agent page.' },
  provider_key_missing: {
    said: 'No key is saved for this model\'s provider.',
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

const FALLBACK = 'The model could not answer. Retry in a moment; if it keeps happening, ask an admin.';

/**
 * The refusal behind `code` for a reader who manages settings (`admin`) or not: the sentence to show and, for an admin
 * whose fix is on a settings page, that page. A code not listed gets the plain fallback and keeps `code` for a details
 * control. Undefined when there is no code: that error is not a model refusal and the caller shows its own message.
 */
export function modelRefusal(code: string | undefined, admin: boolean): { text: string; fixAt?: string; code?: string } | undefined {
  if (!code) return undefined;
  const r = REFUSALS[code];
  if (!r) return { text: FALLBACK, code };
  const action = r.anyone ?? (admin ? r.admin : r.member);
  return { text: action ? `${r.said} ${action}` : r.said, fixAt: admin ? r.fixAt : undefined };
}
