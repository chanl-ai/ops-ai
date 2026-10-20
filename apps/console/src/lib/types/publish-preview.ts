/** A publish's review mode, as the team's publishReview policy sets it. */
export type PublishMode = 'always' | 'major' | 'never';

/** What the team's publish policy would do with a publish, asked before it is made (agents-1). */
export interface PublishPreview {
  reviewRequired: boolean;
  policy: PublishMode;
  majorChange: boolean;
  reviewReason: 'policy_always' | 'security_change' | 'policy_never' | 'major_change' | 'dev_auto_approve' | 'minor_change' | 'policy_unread';
}
