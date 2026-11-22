import type { WorkflowPublishPreview } from '@/lib/types/engine';

/**
 * Whether the publish dialog's Publish (or Send for review) button may be pressed: never before the preview is read,
 * while a send is in flight, or while the preview lists a problem the server would refuse the publish on.
 */
export function canSubmitPublish(preview: Pick<WorkflowPublishPreview, 'blockers'> | undefined, pending: boolean): boolean {
  return !!preview && !pending && preview.blockers.length === 0;
}
