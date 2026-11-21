import { CODES, STATUSES } from './generated/codes.js';

/** A code's row in the one error model's table; an unknown code reads as `internal_error`, as the services read it. */
export function codeOf(code?: string | null): { kind: ErrorKind; retryable: boolean } {
  const row = CODES[code ?? ''] ?? CODES.internal_error ?? { kind: 'internal', retryable: false };
  return { kind: row.kind as ErrorKind, retryable: row.retryable };
}

/** The row the services give a refusal by its status alone (generated from `row_for_status`): read only when a
 * refusal carries no code the table knows and its body names no kind. */
function statusRow(status: number): { kind: string; retryable: boolean } {
  return STATUSES[String(status)] ?? STATUSES[status >= 400 && status < 500 ? '400' : '500']!;
}

export function kindOfStatus(status: number): ErrorKind {
  return statusRow(status).kind as ErrorKind;
}

/** One error class per kind of refusal, each carrying the API's code, message and request id, and the error model's
 * kind and whether a retry helps: from the code's row in the one table, then the body, the status only when neither. */
export class OpsError extends Error {
  readonly kind: ErrorKind;
  readonly retryable: boolean;
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId?: string,
    readonly details?: unknown,
    said: { kind?: ErrorKind; retryable?: boolean } = {},
  ) {
    super(`${status} ${code}: ${message}${requestId ? ` (request ${requestId})` : ''}`);
    this.name = new.target.name;
    const row = CODES[code];
    this.kind = (row?.kind as ErrorKind | undefined) ?? said.kind ?? kindOfStatus(status);
    this.retryable = row?.retryable ?? said.retryable ?? statusRow(status).retryable;
  }
}
/** 400 or 422: the input was refused, including `step_up_required` and `approval_token_required`. */
export class BadRequest extends OpsError {}
/** 401: no key, or a key the platform does not know. */
export class Unauthorized extends OpsError {}
/** 403: the key's person or team may not do this. */
export class Forbidden extends OpsError {}
/** 404, which is also what a team that cannot see a record gets. */
export class NotFound extends OpsError {}
/** 409: the record's state does not allow it, such as a task already decided. */
export class Conflict extends OpsError {}
/** 429: over a budget or rate limit. */
export class RateLimited extends OpsError {}
/** 5xx. */
export class ServerError extends OpsError {}

const BY_STATUS: Record<number, typeof OpsError> = {
  400: BadRequest, 401: Unauthorized, 403: Forbidden, 404: NotFound, 409: Conflict, 422: BadRequest, 429: RateLimited,
};

export function errorFor(status: number, error: Record<string, unknown>, requestId: string | undefined, text: string): OpsError {
  const Cls = BY_STATUS[status] ?? (status >= 500 ? ServerError : OpsError);
  return new Cls(
    status,
    String(error.code ?? 'error'),
    String(error.message ?? (text || 'request refused')),
    (error.requestId as string | undefined) ?? requestId,
    error.details,
    { kind: error.kind as ErrorKind | undefined, retryable: error.retryable as boolean | undefined },
  );
}

/** The one error model's kinds (the agents service's RunFailure): what failed, so a caller knows whose move it is. */
export type ErrorKind = 'input' | 'refused' | 'upstream' | 'timeout' | 'internal';

/** A run's failure as the agents service returns it on the run. */
export interface RunFailure {
  kind: ErrorKind;
  code: string;
  message: string;
  userMessage: string;
  retryable: boolean;
  retryAfterSeconds?: number | null;
  nodeId?: string | null;
  nodeName?: string | null;
  attempt?: number | null;
  of?: number | null;
  traceId?: string | null;
  /** Plain values beside the code: which clock ran out, which End the run reached. */
  details?: Record<string, string | number | boolean | null>;
}

/** A run that failed, thrown by `runs.wait(id, { check: true })`. `message` is for the builder, `userMessage` is safe
 * to show an end user, `retryable` says whether trying again can help. */
export class RunFailed extends Error {
  readonly kind: ErrorKind;
  readonly code: string;
  readonly userMessage: string;
  readonly retryable: boolean;
  readonly retryAfter?: number;
  readonly traceId?: string;
  readonly step?: string;
  constructor(readonly run: { id: string; error?: string | null; failure?: RunFailure | null }) {
    const f = run.failure;
    super(f?.message ?? run.error ?? 'The run failed.');
    this.name = 'RunFailed';
    this.kind = f?.kind ?? 'internal';
    this.code = f?.code ?? 'internal_error';
    this.userMessage = f?.userMessage ?? '';
    this.retryable = Boolean(f?.retryable);
    this.retryAfter = f?.retryAfterSeconds ?? undefined;
    this.traceId = f?.traceId ?? undefined;
    this.step = f?.nodeName ?? f?.nodeId ?? undefined;
  }
}
