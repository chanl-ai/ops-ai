import { failureWords } from '@/lib/failure-words';

/**
 * Why a failed call did not go through, in words, under the call's name in a log's first column: there it wraps and
 * stays on screen at any width, where a status column at a wide table's edge cut it off. Nothing for any other call.
 */
export function FailureReason({ call }: { call: { status: string; errorCode?: string; errorMessage?: string } }) {
  if (call.status !== 'error') return null;
  return (
    <span className="block max-w-full text-xs whitespace-normal text-destructive-text" title={call.errorCode} data-testid="call-failure-words">
      {failureWords(call.errorCode, call.errorMessage)}
    </span>
  );
}
