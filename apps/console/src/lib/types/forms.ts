import type { OpsAI } from '@chanl-ai/ops-ai';

type Agents = OpsAI['raw']['agents'];
type Data<K extends keyof Agents> = Awaited<ReturnType<Agents[K]>>;
type Args<K extends keyof Agents> = NonNullable<Parameters<Agents[K]>[0]>;

/** A workflow's start form shared as a page of its own (`GET /v1/workflows/{id}/forms`); a link's token comes only with the answer that made it. */
export type HostedFormLink = Data<'forms_workflow_forms'>['data'][number];
/** Who may fill a hosted form: anyone holding its signed link, or signed-in members of the form's team. */
export type HostedFormMode = HostedFormLink['mode'];
export type HostedFormInput = Args<'forms_create_form'>['body'];
export type HostedFormPatch = Args<'forms_update_form'>['body'];
/** What a person sees of a form before they send it: its title, description and fields, and the thank-you. */
export type HostedFormView = Data<'forms_member_form'>;
/** A submission the server took; a members-only one names the run it started. */
export type HostedFormReceived = Data<'forms_submit_member'>;
