/**
 * The one card agents show in chat (c-469): a record's type and title, one status, a body of facts or steps, and at
 * most two actions plus More, with Open to the record's own page. Ops tools answer with references; the thread read
 * fills each one in from the record as the reader sees it (agents-service api/ops_tools.py `fill_cards`).
 */

export type CardTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';
export type CardRecordType = 'case' | 'task' | 'run' | 'start' | 'customer';
export type CardStepState = 'pending' | 'running' | 'done' | 'failed';

export interface CardStatus {
  text: string;
  tone: CardTone;
}

export interface CardFact {
  label: string;
  value: string;
  /** Where the value opens, when it names a record. */
  href?: string;
  /** Drawn in the warning colour: the fact the decision turns on. */
  warn?: boolean;
}

export interface CardStep {
  title: string;
  state: CardStepState;
}

export type CardBody = { kind: 'facts'; facts: CardFact[] } | { kind: 'steps'; steps: CardStep[]; facts?: CardFact[] } | { kind: 'none' };

export interface OpsCardSpec {
  id: string;
  record: { type: CardRecordType; label: string; href: string; open: string };
  title: string;
  subtitle?: string;
  status?: CardStatus;
  body: CardBody;
}

/** One card reference on an Ops tool's answer, as the thread read fills it in. */
export interface OpsCardRef {
  type: 'case' | 'task' | 'run' | 'start';
  id: string;
  /** The record's view from its own route, as the reader sees it; absent when `missing`. */
  view?: unknown;
  /** The record is gone or out of the reader's reach. */
  missing?: boolean;
}

/** A card button: what it says and what pressing it does, with the record's own rules already applied. */
export interface CardButton {
  id: string;
  label: string;
  primary?: boolean;
  destructive?: boolean;
  /** Asks for a fresh sign-in before it acts (the record's `stepUp`). */
  locked?: boolean;
  onPress: () => Promise<void> | void;
}
