/** Who may fill a hosted form (c-535): anyone holding its signed link, or signed-in members of the form's team. */
export type HostedFormMode = 'link' | 'members';

/** A workflow's start form shared as a page of its own (agents-service `/v1/workflows/{id}/forms`). */
export interface HostedFormLink {
  id: string;
  workflowId: string;
  slug: string;
  mode: HostedFormMode;
  title: string;
  description: string;
  afterText: string;
  expiresAt: string;
  dailyCap: number;
  paused: boolean;
  /** The page's path, `/f/<slug>`; it carries `?t=<token>` only in the answer that made the token (create or Rotate). */
  url: string;
  /** A link form's token, shown once: the list never returns it. */
  token?: string | null;
}

export interface HostedFormInput {
  mode: HostedFormMode;
  /** 1 to 90; the server's default is 30. */
  expiresInDays?: number;
  /** Submissions a day; the server's default is 200. */
  dailyCap?: number;
  /** Defaults to the workflow's name on the server. */
  title?: string;
  description?: string;
  afterText?: string;
}

export interface HostedFormPatch {
  paused?: boolean;
  dailyCap?: number;
  afterText?: string;
}

/** What a person sees of a form before they send it: its title, description and fields, and the thank-you. */
export interface HostedFormView {
  title: string;
  description: string;
  form: { schema: Record<string, unknown>; takesFiles?: boolean | null };
  afterText: string;
}

/** A submission the server took; a members-only one names the run it started. */
export interface HostedFormReceived {
  received: boolean;
  runId?: string | null;
}
