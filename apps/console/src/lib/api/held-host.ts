import { ApiError } from './contract';

/** tools-service's 202 when an app's address is on a host the tenant has not listed: Security's task is `runKey`. */
export interface HeldHost {
  heldFor: 'security';
  host: string;
  runKey: string;
}

/**
 * Nothing was saved: the address waits on the Security team. Thrown rather than returned so the form that set the
 * address stays open and says so, instead of treating the 202 as the saved record.
 */
export class HostHeldError extends ApiError {
  constructor(
    readonly host: string,
    readonly runKey: string,
  ) {
    super(`Waiting for Security to allow ${host}.`, 202, undefined, 'host_held', { host, runKey });
  }
}

export function unlessHeld<T>(answer: T | HeldHost): T {
  if (answer && typeof answer === 'object' && 'heldFor' in answer) throw new HostHeldError(answer.host, answer.runKey);
  return answer as T;
}
