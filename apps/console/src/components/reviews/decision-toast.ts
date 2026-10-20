import type { Review, ReviewDecision } from '@/lib/types/domain';

/**
 * What the toast says once a review is decided, for the kinds whose payload names what was decided: a tool module
 * publish, and anything else by its own title. Only a paused step (a workflow or chat thread) "resumes"; a publish
 * request has no run to resume, so it never says so.
 */
export function decisionToast(review: Review, decision: ReviewDecision): { title: string; description: string } {
  if (review.toolModule) {
    const name = `${review.workflowName} v${review.toolModule.version}`;
    if (decision === 'approved') return { title: `Published ${name}`, description: 'Agents granted its operations call this version now.' };
    return { title: `${decision === 'rejected' ? 'Rejected' : 'Returned'} ${name}`, description: 'The requester has your reason.' };
  }
  const verb = decision === 'approved' ? 'Approved' : decision === 'rejected' ? 'Rejected' : 'Returned';
  if (review.origin) {
    return {
      title: `${verb} · ${review.id}`,
      description: decision === 'approved' ? 'The run has resumed with your decision.' : 'The agent has the reason.',
    };
  }
  return { title: `${verb} · ${review.title}`, description: decision === 'approved' ? 'Recorded with your name and the time.' : 'The requester has your reason.' };
}
