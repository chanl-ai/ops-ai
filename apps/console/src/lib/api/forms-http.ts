import type { FormsApi } from './forms-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** agents-service's forms routes (routers/forms.py). The public routes are the embed app's, not the console's. */
export function createFormsHttp(get: Get, send: Send): FormsApi {
  const at = (s: string) => encodeURIComponent(s);
  return {
    list: (workflowId) => get(`/workflows/${at(workflowId)}/forms`),
    create: (workflowId, input) => send('POST', `/workflows/${at(workflowId)}/forms`, input),
    rotate: (formId) => send('POST', `/forms/${at(formId)}/rotate`),
    update: (formId, patch) => send('PATCH', `/forms/${at(formId)}`, patch),
    memberForm: (slug) => get(`/forms/${at(slug)}/members`),
    submitMember: (slug, values) => send('POST', `/forms/${at(slug)}/members`, { values }),
    // Without the embed app's address the path is all there is; index.ts prefixes it when NEXT_PUBLIC_OPS_EMBED_URL is set.
    pageUrl: (form) => form.url,
  };
}
