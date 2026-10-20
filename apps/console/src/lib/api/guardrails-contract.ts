import type { Guardrail } from '@/lib/types/domain';
import type { ListParams, ListResult, OptionsPage, OptionsParams } from '@/lib/types/query';

/**
 * Guardrails an agent pins by version (agents-service `/v1/guardrails`, c-063). Kind `blocked_topics` only. A save is a
 * new draft version; agents keep the version they pin. Publishing opens a review decided in Reviews by someone other
 * than whoever asked or saved; in dev it is approved at once.
 */
export interface GuardrailsApi {
  /** Every guardrail, for the agent page's pin picker. */
  list(): Promise<Guardrail[]>;
  /** One page of the guardrails whose name or owner matches the search, by name. */
  page(p: ListParams): Promise<ListResult<Guardrail>>;
  /** The guardrail picker: live, published guardrails searched on the server; `ids` labels pins held (c-136). */
  options(p: OptionsParams): Promise<OptionsPage>;
  /** One guardrail with every version. */
  get(id: string): Promise<Guardrail>;
  create(input: GuardrailInput): Promise<Guardrail>;
  /** Saves the next version as a draft. */
  update(id: string, patch: { topics?: string[]; message?: string; scopes?: Record<string, string>; holdUntilChecked?: boolean; note?: string }): Promise<Guardrail>;
  /** 409 when `version` is not the newest draft. */
  requestPublish(id: string, version: number, note: string): Promise<Guardrail>;
  /** Deprecated: no new pins; agents that pin it keep enforcing their version. */
  setStatus(id: string, status: Guardrail['status']): Promise<Guardrail>;
  /** 409 while an agent pins it. */
  remove(id: string): Promise<void>;
}

export interface GuardrailInput {
  name: string;
  topics: string[];
  /** Topic to what it covers and what it does not; a topic without one is checked by its label alone. */
  scopes?: Record<string, string>;
  message: string;
  holdUntilChecked?: boolean;
  owner: string;
}
