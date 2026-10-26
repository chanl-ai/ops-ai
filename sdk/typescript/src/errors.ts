/** One error class per kind of refusal, each carrying the API's code, message and request id. */
export class OpsError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId?: string,
    readonly details?: unknown,
  ) {
    super(`${status} ${code}: ${message}${requestId ? ` (request ${requestId})` : ''}`);
    this.name = new.target.name;
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
  );
}
