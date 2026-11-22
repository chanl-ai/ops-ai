/**
 * What a line of an agent brief or a skill step can point at, as agents-service's `GET /v1/references` answers
 * (`ReferenceSearch`) and as a publish check reports a problem (`PublishBlocker`). The field names are the wire's, so
 * these become aliases of the SDK's types once the route is in the generated client.
 */
export type RefKind = 'tool' | 'knowledge' | 'skill' | 'agent' | 'workflow';

/** A reference as stored in text: `@kind:id`. */
export interface Ref {
  kind: RefKind;
  id: string;
}

export interface ReferenceItem extends Ref {
  /** The item's current name; a chip shows this, never the id. */
  label: string;
  hint: string | null;
  /** The agent or skill being edited already holds it; null for a kind that is not held. */
  held: boolean | null;
  /** What picking it adds, in product copy, when it is not held. */
  adds: string | null;
  needsApproval: boolean;
  /** Why it cannot be picked, when it cannot. */
  disabled: string | null;
}

export interface ReferenceGroup {
  kind: RefKind;
  label: string;
  items: ReferenceItem[];
  nextCursor: string | null;
}

/** Only kinds the person may view, and only groups with items. */
export interface ReferenceSearch {
  groups: ReferenceGroup[];
}

/** The agent or the skill whose document is being edited: exactly one. */
export type ReferenceContext = { forAgent: string } | { forSkill: string };

export interface BlockerPosition {
  /** For example `brief.purpose`, `brief.never`, `steps`. */
  field: string;
  /** 1-based. */
  step: number | null;
  index: number | null;
}

export interface PublishBlocker {
  kind:
    | 'missing_field'
    | 'missing_reference'
    | 'unavailable_reference'
    | 'bad_step'
    | 'bad_check'
    | 'bad_exit'
    | 'sub_skill_not_held'
    | 'prompt_rule_in_text'
    | 'review_open'
    | 'already_published'
    | 'deprecated'
    | 'too_long'
    | 'eval_failed'
    | 'eval_not_run'
    | 'eval_no_cases'
    | 'eval_setting_unread';
  /** An eval problem carries the gate's steps, worded by the service. */
  details?: { steps: import('./assurance').GateStep[] } | null;
  /** For a reference blocker, `<kind>:<id>`. */
  id: string | null;
  position: BlockerPosition | null;
  message: string;
}

/** A problem the publish check reports but does not block on: the same shape as a blocker, with the service's own kind. */
export type PublishWarning = Omit<PublishBlocker, 'kind'> & { kind: string };

/** The answer of `POST /v1/agents/{id}/references`: what was granted and the version it was saved as. */
export interface AddedReferences {
  added: ReferenceItem[];
  agentVersion: number;
}

/** `GET /v1/agents/{id}/prompt`: the prompt a version gives the model, read only, with Never last. */
export interface AgentPrompt {
  version: number;
  text: string;
}

/** `POST /v1/agents/{id}/brief-draft`: a proposed text per brief heading; nothing is saved until one is accepted. */
export interface BriefDraft {
  job: string;
  howToAnswer: string;
  handOff: string[];
  examples: string;
  never: string[];
}

/** `GET /v1/agents/{id}/publish-check`: whether the newest draft can be sent for publish, and what stops it. */
export interface AgentPublishCheck {
  canRequest: boolean;
  problems: PublishBlocker[];
  /** The same problems in the one shape every publish check returns, in the same order. */
  blockers: Blocker[];
}

/** One reason a publish is refused, in the one shape the agent, skill and workflow publish checks return: the workflow
 * step (`node`) or the field it is in, its level and code, and the sentence the publish dialog shows. */
export interface Blocker {
  node: string | null;
  field: string | null;
  level: 'error' | 'warning';
  code: string;
  message: string;
}
