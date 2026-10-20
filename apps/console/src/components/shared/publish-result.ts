import { toast } from 'sonner';

/**
 * The one message every record page shows after Publish (c-139). The route answers whether the version went live or
 * waits for a second person, under the team's publish-review setting; the page says that and nothing else, so no
 * page claims a review that did not open or a publish that did not happen.
 */
export interface PublishResult {
  name: string;
  version: number | string;
  /** True when the version went live at once. */
  live: boolean;
  /** What changes for people once it is live, e.g. "Agents can pin it now." */
  liveNote: string;
  /** Who decides it while it waits, e.g. "An approver in Operations" or "The Security team". */
  decidedBy: string;
  /** Where they decide it; Reviews unless the record has its own review. */
  where?: string;
  /** The review that opened, when one did. */
  reviewId?: string | null;
  openReview?: (reviewId: string) => void;
}

export function announcePublish({ name, version, live, liveNote, decidedBy, where = 'in Reviews', reviewId, openReview }: PublishResult) {
  if (live) {
    toast.success(`Published ${name} v${version}`, { description: liveNote });
    return;
  }
  toast.success(`Sent ${name} v${version} for review`, {
    description: `${decidedBy} decides it ${where}.`,
    action: reviewId && openReview ? { label: 'Open review', onClick: () => openReview(reviewId) } : undefined,
  });
}
