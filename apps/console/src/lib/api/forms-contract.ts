import type { HostedFormInput, HostedFormLink, HostedFormPatch, HostedFormReceived, HostedFormView } from '@/lib/types/forms';

/**
 * Hosted forms (c-535): a workflow's start form shared as a page. A link form opens in the embed app with its signed
 * token and needs no sign-in; a members-only form opens in the console. Builders of the workflow's team make, rotate
 * and pause them.
 */
export interface FormsApi {
  /** The workflow's forms, without tokens. */
  list(workflowId: string): Promise<HostedFormLink[]>;
  /** 409 `form_needs_inputs` when the live version's trigger declares no inputs. A link form's answer holds its token. */
  create(workflowId: string, input: HostedFormInput): Promise<HostedFormLink>;
  /** A new token; the old link stops working at once. */
  rotate(formId: string): Promise<HostedFormLink>;
  update(formId: string, patch: HostedFormPatch): Promise<HostedFormLink>;
  /** A members-only form for the signed-in person; 403 `form_members_only` outside the form's team. */
  memberForm(slug: string): Promise<HostedFormView>;
  /** Starts a run as the signed-in person. */
  submitMember(slug: string, values: Record<string, unknown>): Promise<HostedFormReceived>;
  /** The full address people open a link form at: the embed app's host (NEXT_PUBLIC_OPS_EMBED_URL) and the form's path. */
  pageUrl(form: HostedFormLink): string;
}
